"""
Comprehensive test suite for the ParameterResolver class.

This test suite covers all aspects of the ParameterResolver's functionality:
- Simple parameter resolution (names/UUIDs to URLs)
- Complex recursive resolution of nested dictionaries and lists
- Dependency-based filtering and caching mechanisms
- Cache priming from existing resources
- Error handling and edge cases

The tests use pytest with mocking to isolate the resolver's logic from
actual API calls and focus on the parameter transformation logic.
"""

from unittest.mock import Mock
from copy import deepcopy

# Import the class under test
from ansible_waldur_generator.interfaces.resolver import ParameterResolver


class TestParameterResolverInitialization:
    """Test the initialization and basic setup of ParameterResolver."""

    def test_init_with_runner(self):
        """Test that ParameterResolver initializes correctly with a runner."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {"resolvers": {}}

        # Act
        resolver = ParameterResolver(mock_runner)

        # Assert
        assert resolver.runner is mock_runner
        assert resolver.module is mock_runner.module
        assert resolver.context is mock_runner.context
        assert resolver.cache == {}

    def test_init_preserves_runner_references(self):
        """Test that the resolver maintains proper references to runner components."""
        # Arrange
        mock_module = Mock()
        mock_context = {"resolvers": {"test": {}}}
        mock_runner = Mock()
        mock_runner.module = mock_module
        mock_runner.context = mock_context

        # Act
        resolver = ParameterResolver(mock_runner)

        # Assert
        assert resolver.module is mock_module
        assert resolver.context is mock_context


class TestCachePriming:
    """Test the cache priming functionality from existing resources."""

    def test_prime_cache_from_resource_single_key(self):
        """Test priming cache with a single dependency key."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {"resolvers": {}}
        mock_runner._send_request = Mock(
            return_value={"uuid": "offering-123", "name": "test-offering"}
        )

        resolver = ParameterResolver(mock_runner)
        resource = {
            "offering": "https://api.waldur.com/api/marketplace-offerings/offering-123/"
        }

        # Act
        resolver.prime_cache_from_resource(resource, ["offering"])

        # Assert
        mock_runner._send_request.assert_called_once_with(
            "GET", "https://api.waldur.com/api/marketplace-offerings/offering-123/"
        )
        assert "offering" in resolver.cache
        assert resolver.cache["offering"]["uuid"] == "offering-123"

    def test_prime_cache_from_resource_multiple_keys(self):
        """Test priming cache with multiple dependency keys."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {"resolvers": {}}

        # Mock different responses for different URLs
        def mock_send_request(method, url):
            if "offerings" in url:
                return {
                    "uuid": "offering-123",
                    "name": "test-offering",
                    "scope_uuid": "tenant-456",
                }
            elif "projects" in url:
                return {"uuid": "project-789", "name": "test-project"}
            return None

        mock_runner._send_request = Mock(side_effect=mock_send_request)

        resolver = ParameterResolver(mock_runner)
        resource = {
            "offering": "https://api.waldur.com/api/marketplace-offerings/offering-123/",
            "project": "https://api.waldur.com/api/projects/project-789/",
        }

        # Act
        resolver.prime_cache_from_resource(resource, ["offering", "project"])

        # Assert
        assert mock_runner._send_request.call_count == 2
        assert "offering" in resolver.cache
        assert "project" in resolver.cache
        assert resolver.cache["offering"]["uuid"] == "offering-123"
        assert resolver.cache["project"]["uuid"] == "project-789"

    def test_prime_cache_skips_missing_keys(self):
        """Test that cache priming skips keys that don't exist on the resource."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {"resolvers": {}}
        mock_runner._send_request = Mock()

        resolver = ParameterResolver(mock_runner)
        resource = {
            "offering": "https://api.waldur.com/api/marketplace-offerings/offering-123/"
        }

        # Act
        resolver.prime_cache_from_resource(resource, ["offering", "nonexistent_key"])

        # Assert
        # Should only call _send_request once for the existing key
        mock_runner._send_request.assert_called_once()
        assert "offering" in resolver.cache
        assert "nonexistent_key" not in resolver.cache

    def test_prime_cache_skips_already_cached(self):
        """Test that cache priming skips keys that are already in cache."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {"resolvers": {}}
        mock_runner._send_request = Mock(return_value={"uuid": "new-data"})

        resolver = ParameterResolver(mock_runner)
        resolver.cache["offering"] = {"uuid": "cached-data"}
        resource = {
            "offering": "https://api.waldur.com/api/marketplace-offerings/offering-123/"
        }

        # Act
        resolver.prime_cache_from_resource(resource, ["offering"])

        # Assert
        # Should not make any API calls since the key is already cached
        mock_runner._send_request.assert_not_called()
        assert resolver.cache["offering"]["uuid"] == "cached-data"


class TestSimpleResolution:
    """Test the resolve_to_url method for simple parameter resolution."""

    def test_resolve_to_url_with_uuid(self):
        """Test resolving a UUID directly to URL without API call."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.module.params = {"api_url": "https://api.waldur.com/"}
        mock_runner.context = {
            "resolvers": {
                "customer": {
                    "url": "/api/customers/",
                    "error_message": "Customer '{value}' not found",
                }
            }
        }
        mock_runner._is_uuid = Mock(return_value=True)

        resolver = ParameterResolver(mock_runner)

        # Act
        result = resolver.resolve_to_url(
            "customer", "123e4567-e89b-12d3-a456-426614174000"
        )

        # Assert
        expected = (
            "https://api.waldur.com/api/customers/123e4567-e89b-12d3-a456-426614174000/"
        )
        assert result == expected
        # Should not make any API calls for UUID resolution
        mock_runner._send_request.assert_not_called()

    def test_resolve_to_url_with_name_single_result(self):
        """Test resolving a name to URL with single API result."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {
            "resolvers": {
                "customer": {
                    "url": "/api/customers/",
                    "error_message": "Customer '{value}' not found",
                }
            }
        }
        mock_runner._is_uuid = Mock(return_value=False)
        mock_runner._send_request = Mock(
            return_value=[
                {
                    "url": "https://api.waldur.com/api/customers/customer-123/",
                    "name": "test-customer",
                }
            ]
        )

        resolver = ParameterResolver(mock_runner)

        # Act
        result = resolver.resolve_to_url("customer", "test-customer")

        # Assert
        mock_runner._send_request.assert_called_once_with(
            "GET", "/api/customers/", query_params={"name_exact": "test-customer"}
        )
        assert result == "https://api.waldur.com/api/customers/customer-123/"

    def test_resolve_to_url_with_name_multiple_results(self):
        """Test resolving a name with multiple results (should warn and use first)."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {
            "resolvers": {
                "project": {
                    "url": "/api/projects/",
                    "error_message": "Project '{value}' not found",
                }
            }
        }
        mock_runner._is_uuid = Mock(return_value=False)
        mock_runner._send_request = Mock(
            return_value=[
                {
                    "url": "https://api.waldur.com/api/projects/project-123/",
                    "name": "test-project",
                },
                {
                    "url": "https://api.waldur.com/api/projects/project-456/",
                    "name": "test-project",
                },
            ]
        )

        resolver = ParameterResolver(mock_runner)

        # Act
        result = resolver.resolve_to_url("project", "test-project")

        # Assert
        mock_runner.module.warn.assert_called_once_with(
            "Multiple resources found for 'test-project' for parameter 'project'. Using the first one."
        )
        assert result == "https://api.waldur.com/api/projects/project-123/"

    def test_resolve_to_url_no_results_fails(self):
        """Test that resolution fails when no results are found."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {
            "resolvers": {
                "customer": {
                    "url": "/api/customers/",
                    "error_message": "Customer '{value}' not found",
                }
            }
        }
        mock_runner._is_uuid = Mock(return_value=False)
        mock_runner._send_request = Mock(return_value=[])

        resolver = ParameterResolver(mock_runner)

        # Act & Assert
        resolver.resolve_to_url("customer", "nonexistent-customer")
        mock_runner.module.fail_json.assert_called_once_with(
            msg="Customer 'nonexistent-customer' not found"
        )

    def test_resolve_to_url_missing_resolver_config_fails(self):
        """Test that resolution fails when no resolver config exists for parameter."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {"resolvers": {}}

        resolver = ParameterResolver(mock_runner)

        # Act & Assert
        resolver.resolve_to_url("unknown_param", "some-value")
        mock_runner.module.fail_json.assert_called_once_with(
            msg="Configuration error: No resolver found for parameter 'unknown_param'."
        )


class TestRecursiveResolution:
    """Test the main recursive resolve method for complex data structures."""

    def test_resolve_primitive_with_resolver(self):
        """Test resolving a primitive value that has a resolver configuration."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {
            "resolvers": {
                "subnet": {
                    "url": "/api/subnets/",
                    "error_message": "Subnet '{value}' not found",
                }
            }
        }

        resolver = ParameterResolver(mock_runner)
        # Mock the single value resolution
        resolver._resolve_single_value = Mock(
            return_value="https://api.waldur.com/api/subnets/subnet-123/"
        )

        # Act
        result = resolver.resolve("subnet", "private-subnet-A")

        # Assert
        resolver._resolve_single_value.assert_called_once_with(
            "subnet", "private-subnet-A", resolver.context["resolvers"]["subnet"]
        )
        assert result == "https://api.waldur.com/api/subnets/subnet-123/"

    def test_resolve_primitive_without_resolver(self):
        """Test resolving a primitive value with no resolver (should return unchanged)."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {"resolvers": {}}

        resolver = ParameterResolver(mock_runner)

        # Act
        result = resolver.resolve("description", "This is a description")

        # Assert
        assert result == "This is a description"

    def test_resolve_dictionary(self):
        """Test recursive resolution of a dictionary structure."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {
            "resolvers": {
                "subnet": {
                    "url": "/api/subnets/",
                    "error_message": "Subnet '{value}' not found",
                }
            }
        }

        resolver = ParameterResolver(mock_runner)
        resolver._resolve_single_value = Mock(
            return_value="https://api.waldur.com/api/subnets/subnet-123/"
        )

        input_dict = {
            "subnet": "private-subnet-A",
            "description": "Port description",
            "floating_ip": True,
        }

        # Act
        result = resolver.resolve("port", input_dict)

        # Assert
        expected = {
            "subnet": "https://api.waldur.com/api/subnets/subnet-123/",
            "description": "Port description",
            "floating_ip": True,
        }
        assert result == expected
        resolver._resolve_single_value.assert_called_once_with(
            "subnet", "private-subnet-A", resolver.context["resolvers"]["subnet"]
        )

    def test_resolve_list_of_primitives_with_is_list_config(self):
        """Test resolving a list of simple values with is_list configuration."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {
            "resolvers": {
                "security_groups": {
                    "url": "/api/security-groups/",
                    "error_message": "Security group '{value}' not found",
                    "is_list": True,
                }
            }
        }

        resolver = ParameterResolver(mock_runner)
        resolver._resolve_single_value = Mock(
            side_effect=[
                "https://api.waldur.com/api/security-groups/sg-123/",
                "https://api.waldur.com/api/security-groups/sg-456/",
            ]
        )

        input_list = ["sg-web", "sg-db"]

        # Act
        result = resolver.resolve("security_groups", input_list)

        # Assert
        expected = [
            "https://api.waldur.com/api/security-groups/sg-123/",
            "https://api.waldur.com/api/security-groups/sg-456/",
        ]
        assert result == expected
        assert resolver._resolve_single_value.call_count == 2

    def test_resolve_list_of_objects(self):
        """Test resolving a list of complex objects (recursive case)."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {
            "resolvers": {
                "subnet": {
                    "url": "/api/subnets/",
                    "error_message": "Subnet '{value}' not found",
                }
            }
        }

        resolver = ParameterResolver(mock_runner)
        resolver._resolve_single_value = Mock(
            side_effect=[
                "https://api.waldur.com/api/subnets/subnet-123/",
                "https://api.waldur.com/api/subnets/subnet-456/",
            ]
        )

        input_list = [
            {"subnet": "private-subnet-A", "description": "Port 1"},
            {"subnet": "private-subnet-B", "description": "Port 2"},
        ]

        # Act
        result = resolver.resolve("ports", input_list)

        # Assert
        expected = [
            {
                "subnet": "https://api.waldur.com/api/subnets/subnet-123/",
                "description": "Port 1",
            },
            {
                "subnet": "https://api.waldur.com/api/subnets/subnet-456/",
                "description": "Port 2",
            },
        ]
        assert result == expected

    def test_resolve_nested_complex_structure(self):
        """Test resolving a deeply nested structure with mixed types."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {
            "resolvers": {
                "subnet": {
                    "url": "/api/subnets/",
                    "error_message": "Subnet '{value}' not found",
                },
                "security_groups": {
                    "url": "/api/security-groups/",
                    "error_message": "Security group '{value}' not found",
                    "is_list": True,
                },
            }
        }

        resolver = ParameterResolver(mock_runner)
        resolver._resolve_single_value = Mock(
            side_effect=[
                "https://api.waldur.com/api/subnets/subnet-123/",
                "https://api.waldur.com/api/security-groups/sg-123/",
                "https://api.waldur.com/api/security-groups/sg-456/",
            ]
        )

        input_data = {
            "ports": [
                {"subnet": "private-subnet-A", "security_groups": ["sg-web", "sg-db"]}
            ],
            "description": "Complex VM configuration",
        }

        # Act
        result = resolver.resolve("vm_config", input_data)

        # Assert
        expected = {
            "ports": [
                {
                    "subnet": "https://api.waldur.com/api/subnets/subnet-123/",
                    "security_groups": [
                        "https://api.waldur.com/api/security-groups/sg-123/",
                        "https://api.waldur.com/api/security-groups/sg-456/",
                    ],
                }
            ],
            "description": "Complex VM configuration",
        }
        assert result == expected


class TestSingleValueResolution:
    """Test the _resolve_single_value method that handles individual parameter resolution."""

    def test_resolve_single_value_basic_resolution(self):
        """Test basic single value resolution without dependencies."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.module.params = {}
        mock_runner.context = {"resolvers": {}}

        resolver = ParameterResolver(mock_runner)
        resolver._build_dependency_filters = Mock(return_value={})
        resolver._resolve_to_list = Mock(
            return_value=[
                {
                    "url": "https://api.waldur.com/api/subnets/subnet-123/",
                    "name": "test-subnet",
                }
            ]
        )

        resolver_conf = {
            "url": "/api/subnets/",
            "error_message": "Subnet '{value}' not found",
        }

        # Act
        result = resolver._resolve_single_value("subnet", "test-subnet", resolver_conf)

        # Assert
        assert result == "https://api.waldur.com/api/subnets/subnet-123/"
        resolver._build_dependency_filters.assert_called_once_with("subnet", [])
        resolver._resolve_to_list.assert_called_once_with(
            "/api/subnets/", "test-subnet", {}
        )

    def test_resolve_single_value_with_dependencies(self):
        """Test single value resolution with dependency filtering."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.module.params = {}
        mock_runner.context = {"resolvers": {}}

        resolver = ParameterResolver(mock_runner)
        resolver._build_dependency_filters = Mock(
            return_value={"tenant_uuid": "tenant-456"}
        )
        resolver._resolve_to_list = Mock(
            return_value=[
                {
                    "url": "https://api.waldur.com/api/flavors/flavor-123/",
                    "name": "test-flavor",
                }
            ]
        )

        resolver_conf = {
            "url": "/api/flavors/",
            "error_message": "Flavor '{value}' not found",
            "filter_by": [
                {
                    "source_param": "offering",
                    "source_key": "scope_uuid",
                    "target_key": "tenant_uuid",
                }
            ],
        }

        # Act
        result = resolver._resolve_single_value("flavor", "test-flavor", resolver_conf)

        # Assert
        assert result == "https://api.waldur.com/api/flavors/flavor-123/"
        resolver._build_dependency_filters.assert_called_once_with(
            "flavor", resolver_conf["filter_by"]
        )
        resolver._resolve_to_list.assert_called_once_with(
            "/api/flavors/", "test-flavor", {"tenant_uuid": "tenant-456"}
        )

    def test_resolve_single_value_uses_cache(self):
        """Test that single value resolution uses cached results when available."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.module.params = {}
        mock_runner.context = {"resolvers": {}}

        resolver = ParameterResolver(mock_runner)
        resolver.cache[("subnet", "test-subnet")] = {
            "url": "https://api.waldur.com/api/subnets/subnet-123/",
            "name": "test-subnet",
        }
        resolver._build_dependency_filters = Mock(return_value={})
        resolver._resolve_to_list = Mock()  # Should not be called

        resolver_conf = {
            "url": "/api/subnets/",
            "error_message": "Subnet '{value}' not found",
        }

        # Act
        result = resolver._resolve_single_value("subnet", "test-subnet", resolver_conf)

        # Assert
        assert result == "https://api.waldur.com/api/subnets/subnet-123/"
        resolver._resolve_to_list.assert_not_called()

    def test_resolve_single_value_is_list_configuration(self):
        """Test single value resolution with is_list and list_item_key configuration."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.module.params = {}
        mock_runner.context = {"resolvers": {}}

        resolver = ParameterResolver(mock_runner)
        resolver._build_dependency_filters = Mock(return_value={})
        resolver._resolve_to_list = Mock(
            return_value=[
                {
                    "url": "https://api.waldur.com/api/security-groups/sg-123/",
                    "name": "sg-web",
                }
            ]
        )

        resolver_conf = {
            "url": "/api/security-groups/",
            "error_message": "Security group '{value}' not found",
            "is_list": True,
            "list_item_key": "security_group",
        }

        # Act
        result = resolver._resolve_single_value(
            "security_groups", "sg-web", resolver_conf
        )

        # Assert
        expected = {
            "security_group": "https://api.waldur.com/api/security-groups/sg-123/"
        }
        assert result == expected

    def test_resolve_single_value_no_results_fails(self):
        """Test that single value resolution fails when no results are found."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.module.params = {}
        mock_runner.context = {"resolvers": {}}

        resolver = ParameterResolver(mock_runner)
        resolver._build_dependency_filters = Mock(return_value={})
        resolver._resolve_to_list = Mock(return_value=[])

        resolver_conf = {
            "url": "/api/subnets/",
            "error_message": "Subnet '{value}' not found",
        }

        # Act & Assert
        resolver._resolve_single_value("subnet", "nonexistent-subnet", resolver_conf)
        mock_runner.module.fail_json.assert_called_once_with(
            msg="Subnet 'nonexistent-subnet' not found"
        )

    def test_resolve_single_value_multiple_results_warns(self):
        """Test that single value resolution warns when multiple results are found."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.module.params = {}
        mock_runner.context = {"resolvers": {}}

        resolver = ParameterResolver(mock_runner)
        resolver._build_dependency_filters = Mock(return_value={})
        resolver._resolve_to_list = Mock(
            return_value=[
                {
                    "url": "https://api.waldur.com/api/subnets/subnet-123/",
                    "name": "test-subnet",
                },
                {
                    "url": "https://api.waldur.com/api/subnets/subnet-456/",
                    "name": "test-subnet",
                },
            ]
        )

        resolver_conf = {
            "url": "/api/subnets/",
            "error_message": "Subnet '{value}' not found",
        }

        # Act
        result = resolver._resolve_single_value("subnet", "test-subnet", resolver_conf)

        # Assert
        assert result == "https://api.waldur.com/api/subnets/subnet-123/"
        mock_runner.module.warn.assert_called_once_with(
            "Multiple resources found for 'test-subnet' for parameter 'subnet'. Using the first one."
        )

    def test_resolve_single_value_caches_result(self):
        """Test that single value resolution caches its results properly."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.module.params = {"subnet": "test-subnet"}  # Make params dict-like
        mock_runner.context = {"resolvers": {}}

        resolver = ParameterResolver(mock_runner)
        resolver._build_dependency_filters = Mock(return_value={})
        resolver._resolve_to_list = Mock(
            return_value=[
                {
                    "url": "https://api.waldur.com/api/subnets/subnet-123/",
                    "name": "test-subnet",
                }
            ]
        )

        resolver_conf = {
            "url": "/api/subnets/",
            "error_message": "Subnet '{value}' not found",
        }

        # Act
        result = resolver._resolve_single_value("subnet", "test-subnet", resolver_conf)

        # Assert
        assert result == "https://api.waldur.com/api/subnets/subnet-123/"
        # Check that both cache entries are created
        assert ("subnet", "test-subnet") in resolver.cache
        assert "subnet" in resolver.cache  # Top-level parameter cache

    def test_resolve_single_value_without_top_level_param_caching(self):
        """Test single value resolution when param is not in module.params."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.module.params = {}  # Empty params - subnet not in top-level
        mock_runner.context = {"resolvers": {}}

        resolver = ParameterResolver(mock_runner)
        resolver._build_dependency_filters = Mock(return_value={})
        resolver._resolve_to_list = Mock(
            return_value=[
                {
                    "url": "https://api.waldur.com/api/subnets/subnet-123/",
                    "name": "nested-subnet",
                }
            ]
        )

        resolver_conf = {
            "url": "/api/subnets/",
            "error_message": "Subnet '{value}' not found",
        }

        # Act
        result = resolver._resolve_single_value(
            "subnet", "nested-subnet", resolver_conf
        )

        # Assert
        assert result == "https://api.waldur.com/api/subnets/subnet-123/"
        # Only tuple cache entry should exist, not top-level
        assert ("subnet", "nested-subnet") in resolver.cache
        assert "subnet" not in resolver.cache  # Should NOT create top-level cache entry


class TestResolveToList:
    """Test the _resolve_to_list helper method."""

    def test_resolve_to_list_with_uuid(self):
        """Test resolving to list using UUID (direct GET request)."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {"resolvers": {}}
        mock_runner._is_uuid = Mock(return_value=True)
        mock_runner._send_request = Mock(
            return_value={
                "uuid": "subnet-123",
                "name": "test-subnet",
                "url": "https://api.waldur.com/api/subnets/subnet-123/",
            }
        )

        resolver = ParameterResolver(mock_runner)

        # Act
        result = resolver._resolve_to_list(
            "/api/subnets/",
            "123e4567-e89b-12d3-a456-426614174000",
            {"tenant_uuid": "tenant-456"},
        )

        # Assert
        mock_runner._send_request.assert_called_once_with(
            "GET", "/api/subnets/123e4567-e89b-12d3-a456-426614174000/"
        )
        expected = [
            {
                "uuid": "subnet-123",
                "name": "test-subnet",
                "url": "https://api.waldur.com/api/subnets/subnet-123/",
            }
        ]
        assert result == expected

    def test_resolve_to_list_with_uuid_not_found(self):
        """Test resolving to list with UUID when resource doesn't exist."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {"resolvers": {}}
        mock_runner._is_uuid = Mock(return_value=True)
        mock_runner._send_request = Mock(return_value=None)

        resolver = ParameterResolver(mock_runner)

        # Act
        result = resolver._resolve_to_list(
            "/api/subnets/", "123e4567-e89b-12d3-a456-426614174000"
        )

        # Assert
        assert result == []

    def test_resolve_to_list_with_name_and_filters(self):
        """Test resolving to list using name with additional query filters."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {"resolvers": {}}
        mock_runner._is_uuid = Mock(return_value=False)
        mock_runner._send_request = Mock(
            return_value=[{"uuid": "subnet-123", "name": "test-subnet"}]
        )

        resolver = ParameterResolver(mock_runner)

        # Act
        result = resolver._resolve_to_list(
            "/api/subnets/", "test-subnet", {"tenant_uuid": "tenant-456"}
        )

        # Assert
        expected_query = {"name_exact": "test-subnet", "tenant_uuid": "tenant-456"}
        mock_runner._send_request.assert_called_once_with(
            "GET", "/api/subnets/", query_params=expected_query
        )
        assert result == [{"uuid": "subnet-123", "name": "test-subnet"}]

    def test_resolve_to_list_with_name_no_filters(self):
        """Test resolving to list using name without additional filters."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {"resolvers": {}}
        mock_runner._is_uuid = Mock(return_value=False)
        mock_runner._send_request = Mock(
            return_value=[{"uuid": "project-123", "name": "test-project"}]
        )

        resolver = ParameterResolver(mock_runner)

        # Act
        result = resolver._resolve_to_list("/api/projects/", "test-project")

        # Assert
        expected_query = {"name_exact": "test-project"}
        mock_runner._send_request.assert_called_once_with(
            "GET", "/api/projects/", query_params=expected_query
        )
        assert result == [{"uuid": "project-123", "name": "test-project"}]

    def test_resolve_to_list_api_returns_none(self):
        """Test resolving to list when API returns None."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {"resolvers": {}}
        mock_runner._is_uuid = Mock(return_value=False)
        mock_runner._send_request = Mock(return_value=None)

        resolver = ParameterResolver(mock_runner)

        # Act
        result = resolver._resolve_to_list("/api/projects/", "test-project")

        # Assert
        assert result == []


class TestComplexIntegrationScenarios:
    """Test complex, real-world scenarios that combine multiple resolver features."""

    def test_vm_creation_with_ports_and_security_groups(self):
        """Test a complex VM creation scenario with ports, subnets, and security groups."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.module.params = {
            "offering": "openstack-offering",
            "project": "test-project",
        }
        mock_runner.context = {
            "resolvers": {
                "offering": {
                    "url": "/api/marketplace-offerings/",
                    "error_message": "Offering '{value}' not found",
                },
                "project": {
                    "url": "/api/projects/",
                    "error_message": "Project '{value}' not found",
                },
                "subnet": {
                    "url": "/api/subnets/",
                    "error_message": "Subnet '{value}' not found",
                    "filter_by": [
                        {
                            "source_param": "offering",
                            "source_key": "scope_uuid",
                            "target_key": "tenant_uuid",
                        }
                    ],
                },
                "security_groups": {
                    "url": "/api/security-groups/",
                    "error_message": "Security group '{value}' not found",
                    "is_list": True,
                    "list_item_key": "url",
                    "filter_by": [
                        {
                            "source_param": "offering",
                            "source_key": "scope_uuid",
                            "target_key": "tenant_uuid",
                        }
                    ],
                },
            }
        }

        # Mock the API responses
        def mock_resolve_to_list(path, value, query_params=None):
            if "offerings" in path:
                return [
                    {
                        "uuid": "offering-123",
                        "scope_uuid": "tenant-456",
                        "url": "/api/marketplace-offerings/offering-123/",
                    }
                ]
            elif "projects" in path:
                return [{"uuid": "project-789", "url": "/api/projects/project-789/"}]
            elif "subnets" in path:
                if value == "private-subnet-A":
                    return [{"uuid": "subnet-123", "url": "/api/subnets/subnet-123/"}]
                elif value == "private-subnet-B":
                    return [{"uuid": "subnet-456", "url": "/api/subnets/subnet-456/"}]
            elif "security-groups" in path:
                if value == "sg-web":
                    return [{"uuid": "sg-123", "url": "/api/security-groups/sg-123/"}]
                elif value == "sg-db":
                    return [{"uuid": "sg-456", "url": "/api/security-groups/sg-456/"}]
                elif value == "sg-admin":
                    return [{"uuid": "sg-789", "url": "/api/security-groups/sg-789/"}]
            return []

        mock_runner._is_uuid = Mock(return_value=False)

        resolver = ParameterResolver(mock_runner)
        resolver._resolve_to_list = Mock(side_effect=mock_resolve_to_list)

        # Complex input structure
        input_data = {
            "ports": [
                {
                    "subnet": "private-subnet-A",
                    "security_groups": ["sg-web", "sg-db"],
                    "description": "Web server port",
                },
                {
                    "subnet": "private-subnet-B",
                    "security_groups": ["sg-admin"],
                    "description": "Admin port",
                },
            ]
        }

        # Act
        # First resolve the dependencies to populate cache
        resolver.resolve("offering", "openstack-offering")
        resolver.resolve("project", "test-project")
        # Then resolve the complex structure
        result = resolver.resolve("vm_config", input_data)

        # Assert
        expected = {
            "ports": [
                {
                    "subnet": "/api/subnets/subnet-123/",
                    "security_groups": [
                        {"url": "/api/security-groups/sg-123/"},
                        {"url": "/api/security-groups/sg-456/"},
                    ],
                    "description": "Web server port",
                },
                {
                    "subnet": "/api/subnets/subnet-456/",
                    "security_groups": [{"url": "/api/security-groups/sg-789/"}],
                    "description": "Admin port",
                },
            ]
        }
        assert result == expected

    def test_update_scenario_with_cache_priming(self):
        """Test an update scenario where cache is primed from existing resource."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.module.params = {"subnet": "new-subnet"}  # Make params dict-like
        mock_runner.context = {
            "resolvers": {
                "subnet": {
                    "url": "/api/subnets/",
                    "error_message": "Subnet '{value}' not found",
                    "filter_by": [
                        {
                            "source_param": "offering",
                            "source_key": "scope_uuid",
                            "target_key": "tenant_uuid",
                        }
                    ],
                }
            }
        }

        # Mock API responses
        def mock_send_request(method, url, data=None):
            if "offerings" in url:
                return {
                    "uuid": "offering-123",
                    "scope_uuid": "tenant-456",
                    "name": "test-offering",
                }
            return None

        def mock_resolve_to_list(path, value, query_params=None):
            if "subnets" in path and value == "new-subnet":
                # Ensure the query includes the tenant filter
                if query_params and query_params.get("tenant_uuid") == "tenant-456":
                    return [{"uuid": "subnet-new", "url": "/api/subnets/subnet-new/"}]
            return []

        mock_runner._send_request = Mock(side_effect=mock_send_request)
        mock_runner._is_uuid = Mock(return_value=False)

        resolver = ParameterResolver(mock_runner)
        resolver._resolve_to_list = Mock(side_effect=mock_resolve_to_list)

        # Existing resource with offering URL
        existing_resource = {
            "uuid": "vm-123",
            "offering": "/api/marketplace-offerings/offering-123/",
            "ports": [{"subnet": "/api/subnets/subnet-old/"}],
        }

        # Act
        # Prime the cache from existing resource
        resolver.prime_cache_from_resource(existing_resource, ["offering"])
        # Resolve new parameter that depends on the cached offering
        result = resolver.resolve("subnet", "new-subnet")

        # Assert
        assert result == "/api/subnets/subnet-new/"
        # Verify that the dependency filter was applied correctly
        resolver._resolve_to_list.assert_called_with(
            "/api/subnets/", "new-subnet", {"tenant_uuid": "tenant-456"}
        )

    def test_error_propagation_through_nested_resolution(self):
        """Test that errors in nested resolution are properly propagated."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {
            "resolvers": {
                "subnet": {
                    "url": "/api/subnets/",
                    "error_message": "Subnet '{value}' not found",
                }
            }
        }

        resolver = ParameterResolver(mock_runner)
        resolver._resolve_to_list = Mock(return_value=[])  # No results found

        input_data = {"ports": [{"subnet": "nonexistent-subnet"}]}

        # Act & Assert
        # The error should propagate from the nested resolution
        resolver.resolve("vm_config", input_data)
        mock_runner.module.fail_json.assert_called_once_with(
            msg="Subnet 'nonexistent-subnet' not found"
        )

    def test_caching_prevents_duplicate_api_calls(self):
        """Test that caching prevents duplicate API calls for the same parameter."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.module.params = {}
        mock_runner.context = {
            "resolvers": {
                "subnet": {
                    "url": "/api/subnets/",
                    "error_message": "Subnet '{value}' not found",
                }
            }
        }

        resolver = ParameterResolver(mock_runner)
        resolver._build_dependency_filters = Mock(return_value={})
        resolver._resolve_to_list = Mock(
            return_value=[{"uuid": "subnet-123", "url": "/api/subnets/subnet-123/"}]
        )

        resolver_conf = resolver.context["resolvers"]["subnet"]

        # Act
        # Resolve the same parameter twice
        result1 = resolver._resolve_single_value(
            "subnet", "shared-subnet", resolver_conf
        )
        result2 = resolver._resolve_single_value(
            "subnet", "shared-subnet", resolver_conf
        )

        # Assert
        assert result1 == "/api/subnets/subnet-123/"
        assert result2 == "/api/subnets/subnet-123/"
        # API should only be called once due to caching
        resolver._resolve_to_list.assert_called_once()


class TestEdgeCasesAndErrorHandling:
    """Test edge cases, error conditions, and boundary scenarios."""

    def test_resolve_none_value(self):
        """Test resolving None values returns None unchanged."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {"resolvers": {}}

        resolver = ParameterResolver(mock_runner)

        # Act
        result = resolver.resolve("any_param", None)

        # Assert
        assert result is None

    def test_resolve_empty_list(self):
        """Test resolving empty lists returns empty list."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {"resolvers": {}}

        resolver = ParameterResolver(mock_runner)

        # Act
        result = resolver.resolve("any_param", [])

        # Assert
        assert result == []

    def test_resolve_empty_dict(self):
        """Test resolving empty dictionaries returns empty dict."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {"resolvers": {}}

        resolver = ParameterResolver(mock_runner)

        # Act
        result = resolver.resolve("any_param", {})

        # Assert
        assert result == {}

    def test_resolve_mixed_types_in_list(self):
        """Test resolving lists with mixed primitive and object types."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {
            "resolvers": {
                "subnet": {
                    "url": "/api/subnets/",
                    "error_message": "Subnet '{value}' not found",
                }
            }
        }

        resolver = ParameterResolver(mock_runner)
        resolver._resolve_single_value = Mock(return_value="/api/subnets/subnet-123/")

        # Mixed list with dict and primitive
        input_list = [
            {"subnet": "test-subnet", "description": "Port 1"},
            "some-string-value",
        ]

        # Act
        result = resolver.resolve("mixed_list", input_list)

        # Assert
        expected = [
            {"subnet": "/api/subnets/subnet-123/", "description": "Port 1"},
            "some-string-value",
        ]
        assert result == expected

    def test_deep_nesting_resolution(self):
        """Test resolution of deeply nested data structures."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {
            "resolvers": {
                "subnet": {
                    "url": "/api/subnets/",
                    "error_message": "Subnet '{value}' not found",
                }
            }
        }

        resolver = ParameterResolver(mock_runner)
        resolver._resolve_single_value = Mock(return_value="/api/subnets/subnet-123/")

        # Very deeply nested structure
        input_data = {
            "level1": {"level2": {"level3": [{"level4": {"subnet": "deep-subnet"}}]}}
        }

        # Act
        result = resolver.resolve("deep_config", input_data)

        # Assert
        expected = {
            "level1": {
                "level2": {
                    "level3": [{"level4": {"subnet": "/api/subnets/subnet-123/"}}]
                }
            }
        }
        assert result == expected

    def test_immutability_of_input_data(self):
        """Test that the original input data is not modified during resolution."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {
            "resolvers": {
                "subnet": {
                    "url": "/api/subnets/",
                    "error_message": "Subnet '{value}' not found",
                }
            }
        }

        resolver = ParameterResolver(mock_runner)
        resolver._resolve_single_value = Mock(return_value="/api/subnets/subnet-123/")

        # Original input data
        original_input = {"subnet": "test-subnet", "description": "Original port"}
        input_copy = deepcopy(original_input)

        # Act
        result = resolver.resolve("port", input_copy)

        # Assert
        # Original input should be unchanged
        assert original_input == {
            "subnet": "test-subnet",
            "description": "Original port",
        }
        # Result should be different
        expected = {
            "subnet": "/api/subnets/subnet-123/",
            "description": "Original port",
        }
        assert result == expected
        assert result != original_input

    def test_numeric_and_boolean_values_preserved(self):
        """Test that numeric and boolean values are preserved during resolution."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.context = {"resolvers": {}}

        resolver = ParameterResolver(mock_runner)

        input_data = {
            "cpu_count": 4,
            "memory_gb": 8.5,
            "enable_floating_ip": True,
            "auto_assign_ip": False,
            "tags": ["web", "production"],
            "metadata": {"priority": 1, "cost_center": "engineering"},
        }

        # Act
        result = resolver.resolve("vm_spec", input_data)

        # Assert
        # All values should be preserved exactly
        assert result == input_data
        assert isinstance(result["cpu_count"], int)
        assert isinstance(result["memory_gb"], float)
        assert isinstance(result["enable_floating_ip"], bool)
        assert isinstance(result["auto_assign_ip"], bool)


class TestPerformanceAndOptimization:
    """Test performance-related aspects and optimizations."""

    def test_uuid_optimization_avoids_search(self):
        """Test that UUID resolution bypasses search API calls."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.module.params = {"api_url": "https://api.waldur.com"}
        mock_runner.context = {
            "resolvers": {
                "project": {
                    "url": "/api/projects/",
                    "error_message": "Project '{value}' not found",
                }
            }
        }
        mock_runner._is_uuid = Mock(return_value=True)
        mock_runner._send_request = Mock()  # Should not be called

        resolver = ParameterResolver(mock_runner)

        # Act
        result = resolver.resolve_to_url(
            "project", "123e4567-e89b-12d3-a456-426614174000"
        )

        # Assert
        expected = (
            "https://api.waldur.com/api/projects/123e4567-e89b-12d3-a456-426614174000/"
        )
        assert result == expected
        # No API calls should have been made
        mock_runner._send_request.assert_not_called()

    def test_cache_hit_avoids_api_call(self):
        """Test that cache hits avoid redundant API calls."""
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.module.params = {}
        mock_runner.context = {
            "resolvers": {
                "subnet": {
                    "url": "/api/subnets/",
                    "error_message": "Subnet '{value}' not found",
                }
            }
        }

        resolver = ParameterResolver(mock_runner)
        # Pre-populate cache
        resolver.cache[("subnet", "cached-subnet")] = {
            "uuid": "subnet-123",
            "url": "/api/subnets/subnet-123/",
        }

        resolver._resolve_to_list = Mock()  # Should not be called

        # Act
        result = resolver._resolve_single_value(
            "subnet", "cached-subnet", resolver.context["resolvers"]["subnet"]
        )

        # Assert
        assert result == "/api/subnets/subnet-123/"
        resolver._resolve_to_list.assert_not_called()
