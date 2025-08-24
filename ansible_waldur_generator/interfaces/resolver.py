"""
This module contains the ParameterResolver class, a centralized utility for
handling the complex, recursive resolution of Ansible module parameters.

The primary responsibility of this class is to convert user-friendly inputs,
such as resource names or UUIDs, into the specific data structures required by
the Waldur API, typically full resource URLs. By encapsulating this logic,
we achieve a clean separation of concerns, making the runners (like OrderRunner
and CrudRunner) simpler and more focused on their state management tasks.

This class is designed to be instantiated by a runner and operates using
composition, leveraging the runner's access to the Ansible module, its context,
and its API request helper.
"""

from copy import deepcopy


class ParameterResolver:
    """
    A dedicated class to handle the complex, recursive resolution of Ansible
    module parameters. It centralizes the logic for converting user-friendly
    names/UUIDs into API-ready URLs or other data structures.

    This class supports:
    - Simple, non-recursive resolution for basic foreign keys.
    - Recursive resolution of nested dictionaries and lists.
    - Caching of API responses to avoid redundant network requests and to
      facilitate dependency lookups.
    - Dependency-based filtering, allowing the results of one resolved parameter
      to filter the search for another (e.g., filtering flavors by a resolved offering's tenant).
    """

    def __init__(self, runner):
        """
        Initializes the resolver.

        Args:
            runner: The runner instance (e.g., OrderRunner, CrudRunner) that owns this resolver.
                    This provides access to the Ansible module for error reporting, the context
                    for resolver configuration, and the `_send_request` helper for API calls.
        """
        self.runner = runner
        self.module = runner.module
        self.context = runner.context

        # The cache is a critical component for both performance and functionality.
        # - Performance: It stores the full API responses of resolved objects, so if the same
        #   resource (e.g., a project) is needed multiple times, it's only fetched once.
        # - Functionality: It holds the state needed for dependency filtering. For example,
        #   after 'offering' is resolved, its full object is stored here, making its
        #   'scope_uuid' available for filtering a subsequent 'flavor' lookup.
        self.cache = {}

    def prime_cache_from_resource(self, resource: dict, keys: list[str]):
        """
        Primes the resolver's cache with top-level dependency objects from an
        existing resource's data.

        This is primarily used in update scenarios. When updating a resource, we
        already have the URLs for its dependencies (like 'offering' and 'project').
        This method fetches the full objects for those dependencies and loads them
        into the cache, making them immediately available for filtering any nested
        parameters that the user wants to update (e.g., resolving a new 'subnet'
        name requires the 'offering's scope).

        Args:
            resource: The dictionary representing the existing Waldur resource.
            keys: A list of keys on the resource object (e.g., ["offering", "project"])
                  to proactively fetch and cache.
        """
        for key in keys:
            # Check if the resource has the key and we haven't already cached it.
            if resource.get(key) and key not in self.cache:
                # The value (e.g., resource['offering']) is a URL.
                # We make a GET request to that URL to fetch the full object.
                obj_data, _ = self.runner._send_request("GET", resource[key])
                if obj_data:
                    self.cache[key] = obj_data

    def resolve_to_url(self, param_name: str, value: str) -> str:
        """
        A simple, non-recursive method to resolve a name or UUID to its full API URL.

        This method is ideal for basic foreign keys, such as those used in the
        `CrudRunner` for resolving a 'customer' or 'project_type' parameter.

        Args:
            param_name: The name of the parameter being resolved (e.g., "customer").
            value: The user-provided name or UUID string.

        Returns:
            The fully qualified URL of the resolved resource.
        """
        # Retrieve the specific resolver configuration for this parameter from the context.
        resolver_conf = self.context.get("resolvers", {}).get(param_name)
        if not resolver_conf:
            self.module.fail_json(
                msg=f"Configuration error: No resolver found for parameter '{param_name}'."
            )
            return ""  # Unreachable

        # Optimization: If the user provides a UUID, we can construct the URL
        # directly without a search query, which is much more efficient.
        if self.runner._is_uuid(value):
            api_url = self.module.params["api_url"].rstrip("/")
            list_path = resolver_conf["url"].strip("/")
            return f"{api_url}/{list_path}/{value}/"

        # If it's a name, perform a search using the configured list endpoint.
        response, _ = self.runner._send_request(
            "GET", resolver_conf["url"], query_params={"name_exact": value}
        )

        # Handle the results of the search.
        if not response:
            error_template = (
                resolver_conf.get("error_message") or "Resource '{value}' not found."
            )
            error_msg = error_template.format(value=value)
            self.module.fail_json(msg=error_msg)
            return ""  # Unreachable

        if len(response) > 1:
            self.module.warn(
                f"Multiple resources found for '{value}' for parameter '{param_name}'. Using the first one."
            )

        # Return the 'url' field from the first matching resource.
        return response[0]["url"]

    def resolve(
        self, param_name: str, param_value: any, output_format: str = "create"
    ) -> any:
        """
        Recursively traverses a parameter's value structure (which can be a
        dictionary, a list, or a primitive) and resolves any fields that have
        a configured resolver.

        This is the main, powerful entry point for complex resolution, as used
        in the `OrderRunner`. It acts as a "walker" or "traversal engine."

        Args:
            param_name: The name of the current parameter context (e.g., "ports").
            param_value: The data structure provided by the user for this parameter.
            output_format: A hint for the desired output format ('create' or 'update_action').

        Returns:
            The fully resolved data structure, with all names/UUIDs replaced by
            their API-ready, formatted values.
        """
        resolver_conf = self.context["resolvers"].get(param_name)

        # --- Recursive Cases ---

        # Case 1: The value is a dictionary (e.g., a single item from a `ports` list).
        if isinstance(param_value, dict):
            resolved_dict = deepcopy(param_value)
            # Iterate through the dictionary's items and recurse. The dictionary key
            # becomes the new `param_name` context for the next level down.
            for key, value in param_value.items():
                # Pass the hint down during recursion
                resolved_dict[key] = self.resolve(
                    key, value, output_format=output_format
                )
            return resolved_dict

        # Case 2: The value is a list.
        if isinstance(param_value, list):
            # This is a critical distinction:
            # A) A list of simple, resolvable items (e.g., security_groups: ['sg-web', 'sg-db']).
            #    The resolver config for `security_groups` will have `is_list: true`.
            if resolver_conf and resolver_conf.get("is_list"):
                return [
                    self._resolve_single_value(
                        param_name, item, resolver_conf, output_format=output_format
                    )
                    for item in param_value
                ]
            # B) A list of complex objects (e.g., ports: [{'subnet': 'net-A'}, {'subnet': 'net-B'}]).
            #    We just recurse into each object in the list.
            else:
                return [
                    self.resolve(param_name, item, output_format=output_format)
                    for item in param_value
                ]

        # --- Base Case ---

        # Case 3: The value is a primitive (string, int, etc.).
        # If a resolver exists for it, delegate the work to the single-value resolver.
        if resolver_conf:
            return self._resolve_single_value(
                param_name, param_value, resolver_conf, output_format=output_format
            )

        # If it's a primitive with no resolver, return it unchanged.
        return param_value

    def _resolve_single_value(
        self,
        param_name: str,
        value: any,
        resolver_conf: dict,
        output_format: str = "create",
    ) -> any:
        """
        Resolves a single primitive value (name/UUID) into its final, API-ready representation.
        This is the core worker method that performs the API lookups, handles dependencies,
        manages the cache, and formats the output based on the provided hint.

        Args:
            param_name: The name of the parameter being resolved (e.g., "subnet").
            value: The primitive value provided by the user (e.g., "private-subnet-A").
            resolver_conf: The full configuration for this resolver from the context.
            output_format: A hint for the desired output format ('create' or 'update_action').

        Returns:
            The resolved and formatted value, ready for the API payload.
        """
        # Step 1: Build a dictionary of query parameters needed for this lookup
        # by checking for `filter_by` dependencies.
        query_params = self._build_dependency_filters(
            param_name, resolver_conf.get("filter_by", [])
        )

        # Step 2: Check the cache first to avoid a network call.
        # Use a tuple as a cache key to distinguish between different resolutions for the
        # same parameter name (e.g., resolving two different subnets in a `ports` list).
        cache_key = (param_name, value)
        if cache_key in self.cache:
            resolved_object = self.cache[cache_key]
        else:
            # If not in cache, perform the API lookup.
            resource_list = self._resolve_to_list(
                resolver_conf["url"], value, query_params
            )

            if not resource_list:
                error_template = (
                    resolver_conf.get("error_message")
                    or "Resource '{value}' not found."
                )
                self.module.fail_json(msg=error_template.format(value=value))
                return None  # Unreachable
            if len(resource_list) > 1:
                self.module.warn(
                    f"Multiple resources found for '{value}' for parameter '{param_name}'. Using the first one."
                )

            resolved_object = resource_list[0]

            # Step 3: Populate the cache with the new result.
            self.cache[cache_key] = resolved_object
            # For top-level parameters (like 'project' or 'offering'), also cache by the
            # simple parameter name for easy access by dependent resolvers.
            if param_name in self.module.params:
                self.cache[param_name] = resolved_object

        # Step 4: Format the return value based on the resolver's configuration and context hint.
        if resolver_conf.get("is_list"):
            # Use the new context-aware dictionary
            list_item_keys = resolver_conf.get("list_item_keys", {})
            # Get the specific key for the current format ('create' or 'update_action')
            item_key = list_item_keys.get(output_format)

            # If item_key is a string (like 'url'), wrap the URL in an object.
            # If item_key is None, this condition is false, and we fall through.
            if item_key:
                return {item_key: resolved_object["url"]}

        # For non-list resolvers, or for list resolvers where the format is a raw string,
        # return the direct URL.
        return resolved_object["url"]

    def _build_dependency_filters(self, name: str, dependencies: list) -> dict:
        """
        Builds a query parameter dictionary from resolver dependencies by looking
        up previously resolved objects in the cache.

        Args:
            name: The name of the parameter currently being resolved (for error messages).
            dependencies: The list of `filter_by` configurations.

        Returns:
            A dictionary of query parameters (e.g., `{'tenant_uuid': '...'}`).
        """
        query_params = {}
        for dep in dependencies:
            source_param = dep["source_param"]

            # This is a critical check. The dependency (e.g., 'offering') *must* have
            # been resolved and cached before the dependent (e.g., 'flavor') is resolved.
            if source_param not in self.cache:
                self.module.fail_json(
                    msg=f"Configuration error: Resolver for '{name}' depends on '{source_param}', which has not been resolved yet. This may be due to a missing parameter or an incorrect ordering in the module logic."
                )
                return {}  # Unreachable

            source_object = self.cache[source_param]
            source_value = source_object.get(dep["source_key"])

            if source_value is None:
                self.module.fail_json(
                    msg=f"Could not find key '{dep['source_key']}' in the cached response for '{source_param}'. Available keys: {list(source_object.keys())}"
                )
                return {}

            # Map the extracted value to the target query parameter key.
            query_params[dep["target_key"]] = source_value
        return query_params

    def _resolve_to_list(
        self, path: str, value: any, query_params: dict = None
    ) -> list:
        """
        A robust helper to resolve a name or UUID to a list of matching resources,
        applying any provided query filters. It intelligently handles both direct
        fetches by UUID and filtered searches by name.

        Args:
            path: The base API list path for the resource type.
            value: The user-provided name or UUID.
            query_params: A dictionary of pre-built query parameters (e.g., from dependency filters).

        Returns:
            A list of matching resource dictionaries. Guarantees returning a list,
            even if it's empty, to prevent TypeErrors in calling methods.
        """
        # A direct GET by UUID is more efficient and specific than a search.
        if self.runner._is_uuid(value):
            # A GET to a specific resource returns a dict, not a list. We must
            # normalize this into a list to fulfill this method's contract.
            resource, _ = self.runner._send_request(
                "GET", f"{path.rstrip('/')}/{value}/"
            )
            return [resource] if resource else []

        # For name-based lookups, combine the name filter with any dependency filters.
        final_query = query_params.copy() if query_params else {}
        final_query["name_exact"] = value

        # The `_send_request` helper is designed to return an empty list for 204 or empty
        # JSON array responses, which simplifies handling here.
        result, _ = self.runner._send_request("GET", path, query_params=final_query)

        # Ensure we always return a list.
        return result if result is not None else []
