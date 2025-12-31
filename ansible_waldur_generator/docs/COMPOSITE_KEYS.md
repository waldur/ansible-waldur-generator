# Composite Keys and Object Lookup Guide

This guide explains how the Ansible Waldur Generator handles resource lookups using **Composite Keys**. This feature allows resources to be uniquely identified by a combination of multiple fields (e.g., `network` + `target_tenant`) rather than just a single `name` or `uuid`.

## Overview

By default, the generator creates modules that look up resources using:

1. **UUID**: If provided.
2. **Name**: If `name` is provided.
3. **Dependency Filters**: If configured (e.g., finding a subnet by name *within* a specific tenant).

However, some resources (like `network_rbac_policy`) do not have a `name` field or are only unique when multiple attributes are combined. **Composite Keys** solve this by defining a strict set of required parameters that must be provided to effectively "find" the resource.

## Configuration

To enable composite keys for a resource, update the `generator_config.yaml`.

### Field Definition

Add the `composite_keys` list to the resource configuration.

```yaml
resources:
  - os_resource_type: "OS::Neutron::RBACPolicy"
    waldur_resource_type: "OpenStack.NetworkRBACPolicy"
    # ... other config ...
    composite_keys:
      - "network"
      - "target_tenant"
```

In this example:

* The module will require **both** `network` and `target_tenant` to be present to check if the policy exists.
* The `check_existence` logic will resolve these keys (if they are foreign keys) to their UUIDs and use them as query parameters.

### Resolver Mapping

Ensure that any foreign keys used in `composite_keys` have a corresponding resolver that maps to the correct API query parameter.

```yaml
resolvers:
  target_tenant:
    url: "/api/openstack-tenants/"
    # Maps the resolved object's UUID to the 'target_tenant_uuid' query param
    check_filter_keys:
      target_tenant: "target_tenant_uuid"
```

## How It Works

When `runner.run()` executes:

1. **Direct UUID Check**: If `uuid` is provided, it takes precedence.
2. **Composite Key Check**: If `composite_keys` is configured:
   * The runner iterates through each key in the list.
   * It verifies the parameter is present in the user's playbook.
   * It resolves the parameter value (e.g., converting "my-tenant" string to a UUID).
   * It constructs a query using the mapped filter keys (e.g., `?network_uuid=...&target_tenant_uuid=...`).
   * It performs a `GET` request.
     * **Empty List**: Resource does not exist (Create flow).
     * **One Item**: Resource exists (Update/Idempotent flow).
     * **Multiple Items**: Error (Non-unique identification).
