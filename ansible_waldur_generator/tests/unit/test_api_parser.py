"""Tests for the ApiSpecParser class."""

import pytest
from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.helpers import ValidationErrorCollector


class TestApiSpecParser:
    """Test suite for the ApiSpecParser class."""

    @pytest.fixture
    def sample_api_spec(self):
        """Realistic OpenAPI specification based on actual Waldur API."""
        return {
            "openapi": "3.0.3",
            "info": {"title": "Waldur API", "version": "0.0.0"},
            "paths": {
                "/api/customers/": {
                    "get": {
                        "operationId": "customers_list",
                        "description": "To get a list of customers, run GET against /api/customers/ as authenticated user.",
                        "parameters": [
                            {
                                "name": "name",
                                "in": "query",
                                "schema": {"type": "string"},
                            },
                            {
                                "name": "name_exact",
                                "in": "query",
                                "schema": {"type": "string"},
                            },
                            {
                                "name": "abbreviation",
                                "in": "query",
                                "schema": {"type": "string"},
                            },
                            {
                                "name": "archived",
                                "in": "query",
                                "schema": {"type": "boolean"},
                            },
                            {
                                "name": "backend_id",
                                "in": "query",
                                "schema": {"type": "string"},
                            },
                        ],
                        "tags": ["customers"],
                        "responses": {
                            "200": {
                                "description": "",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "array",
                                            "items": {
                                                "$ref": "#/components/schemas/Customer"
                                            },
                                        }
                                    }
                                },
                            }
                        },
                    },
                    "post": {
                        "operationId": "customers_create",
                        "description": "A new customer can only be created by users with staff privilege",
                        "tags": ["customers"],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/CustomerRequest"
                                    },
                                    "examples": {
                                        "CreateCustomer": {
                                            "value": {
                                                "name": "Customer A",
                                                "native_name": "Customer A",
                                                "abbreviation": "CA",
                                                "contact_details": "Luhamaa 28, 10128 Tallinn",
                                            },
                                            "summary": "Create customer",
                                        }
                                    },
                                }
                            },
                            "required": True,
                        },
                        "responses": {
                            "201": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "#/components/schemas/Customer"
                                        }
                                    }
                                },
                                "description": "",
                            }
                        },
                    },
                },
                "/api/customers/{uuid}/": {
                    "get": {
                        "operationId": "customers_retrieve",
                        "parameters": [
                            {
                                "name": "uuid",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string", "format": "uuid"},
                            }
                        ],
                        "tags": ["customers"],
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "#/components/schemas/Customer"
                                        }
                                    }
                                },
                                "description": "",
                            }
                        },
                    },
                    "patch": {
                        "operationId": "customers_partial_update",
                        "parameters": [
                            {
                                "name": "uuid",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string", "format": "uuid"},
                            }
                        ],
                        "tags": ["customers"],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/CustomerRequest"
                                    }
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "#/components/schemas/Customer"
                                        }
                                    }
                                },
                                "description": "",
                            }
                        },
                    },
                    "delete": {
                        "operationId": "customers_destroy",
                        "parameters": [
                            {
                                "name": "uuid",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string", "format": "uuid"},
                            }
                        ],
                        "tags": ["customers"],
                        "responses": {"204": {"description": "No response body"}},
                    },
                },
                "/api/projects/": {
                    "get": {
                        "operationId": "projects_list",
                        "description": "Mixin to optimize HEAD requests for DRF views bypassing serializer processing",
                        "parameters": [
                            {
                                "name": "backend_id",
                                "in": "query",
                                "schema": {"type": "string"},
                            },
                            {
                                "name": "customer",
                                "in": "query",
                                "schema": {"type": "string", "format": "uri"},
                            },
                            {
                                "name": "customer_uuid",
                                "in": "query",
                                "schema": {"type": "string", "format": "uuid"},
                            },
                        ],
                        "tags": ["projects"],
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "array",
                                            "items": {
                                                "$ref": "#/components/schemas/Project"
                                            },
                                        }
                                    }
                                },
                                "description": "",
                            }
                        },
                    },
                    "post": {
                        "operationId": "projects_create",
                        "description": "A new project can be created by users with staff privilege (is_staff=True) or customer owners.",
                        "tags": ["projects"],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/ProjectRequest"
                                    }
                                }
                            },
                            "required": True,
                        },
                        "responses": {
                            "201": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "#/components/schemas/Project"
                                        }
                                    }
                                },
                                "description": "",
                            }
                        },
                    },
                },
                "/api/projects/{uuid}/": {
                    "get": {
                        "operationId": "projects_retrieve",
                        "parameters": [
                            {
                                "name": "uuid",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string", "format": "uuid"},
                            }
                        ],
                        "tags": ["projects"],
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "#/components/schemas/Project"
                                        }
                                    }
                                },
                                "description": "",
                            }
                        },
                    },
                    "patch": {
                        "operationId": "projects_partial_update",
                        "parameters": [
                            {
                                "name": "uuid",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string", "format": "uuid"},
                            }
                        ],
                        "tags": ["projects"],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/ProjectRequest"
                                    }
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "#/components/schemas/Project"
                                        }
                                    }
                                },
                                "description": "",
                            }
                        },
                    },
                    "delete": {
                        "operationId": "projects_destroy",
                        "description": "If a project has connected instances, deletion request will fail with 409 response code.",
                        "parameters": [
                            {
                                "name": "uuid",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string", "format": "uuid"},
                            }
                        ],
                        "tags": ["projects"],
                        "responses": {"204": {"description": "No response body"}},
                    },
                },
            },
            "components": {
                "schemas": {
                    "Customer": {
                        "type": "object",
                        "description": "",
                        "properties": {
                            "url": {
                                "type": "string",
                                "format": "uri",
                                "readOnly": True,
                            },
                            "uuid": {
                                "type": "string",
                                "format": "uuid",
                                "readOnly": True,
                            },
                            "created": {
                                "type": "string",
                                "format": "date-time",
                                "readOnly": True,
                            },
                            "display_name": {"type": "string", "readOnly": True},
                            "backend_id": {
                                "type": "string",
                                "description": "Organization identifier in another application.",
                                "maxLength": 255,
                            },
                            "blocked": {"type": "boolean", "readOnly": True},
                            "archived": {"type": "boolean", "readOnly": True},
                            "name": {"type": "string", "maxLength": 150},
                            "native_name": {"type": "string", "maxLength": 500},
                            "abbreviation": {"type": "string", "maxLength": 12},
                            "contact_details": {"type": "string"},
                            "projects_count": {"type": "integer", "readOnly": True},
                            "users_count": {"type": "integer", "readOnly": True},
                        },
                        "required": ["name"],
                    },
                    "CustomerRequest": {
                        "type": "object",
                        "properties": {
                            "backend_id": {
                                "type": "string",
                                "description": "Organization identifier in another application.",
                                "maxLength": 255,
                            },
                            "name": {"type": "string", "maxLength": 150},
                            "native_name": {"type": "string", "maxLength": 500},
                            "abbreviation": {"type": "string", "maxLength": 12},
                            "contact_details": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                    "Project": {
                        "type": "object",
                        "description": "",
                        "properties": {
                            "url": {
                                "type": "string",
                                "format": "uri",
                                "readOnly": True,
                            },
                            "uuid": {
                                "type": "string",
                                "format": "uuid",
                                "readOnly": True,
                            },
                            "name": {"type": "string", "maxLength": 500},
                            "customer": {
                                "type": "string",
                                "format": "uri",
                                "title": "Organization",
                            },
                            "customer_uuid": {
                                "type": "string",
                                "format": "uuid",
                                "readOnly": True,
                            },
                            "customer_name": {"type": "string", "readOnly": True},
                            "description": {"type": "string"},
                            "created": {
                                "type": "string",
                                "format": "date-time",
                                "readOnly": True,
                            },
                            "type": {
                                "type": "string",
                                "format": "uri",
                                "nullable": True,
                                "title": "Project type",
                            },
                            "backend_id": {"type": "string", "maxLength": 255},
                        },
                        "required": ["name", "customer"],
                    },
                    "ProjectRequest": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "maxLength": 500},
                            "customer": {
                                "type": "string",
                                "format": "uri",
                                "title": "Organization",
                            },
                            "description": {"type": "string"},
                            "type": {
                                "type": "string",
                                "format": "uri",
                                "nullable": True,
                                "title": "Project type",
                            },
                            "backend_id": {"type": "string", "maxLength": 255},
                        },
                        "required": ["name", "customer"],
                    },
                }
            },
        }

    @pytest.fixture
    def parser(self, sample_api_spec):
        """Create an ApiSpecParser instance."""
        collector = ValidationErrorCollector()
        return ApiSpecParser(sample_api_spec, collector)

    def test_initialization(self, sample_api_spec):
        """Test ApiSpecParser initialization."""
        collector = ValidationErrorCollector()
        parser = ApiSpecParser(sample_api_spec, collector)
        assert parser.api_spec == sample_api_spec
        assert parser.collector == collector

    def test_get_operation(self, parser):
        """Test getting operations by operation ID."""
        # Test customers operations
        customers_list = parser.get_operation("customers_list")
        assert customers_list is not None
        assert customers_list.path == "/api/customers/"
        assert customers_list.method == "GET"
        assert customers_list.operation_id == "customers_list"

        customers_create = parser.get_operation("customers_create")
        assert customers_create is not None
        assert customers_create.path == "/api/customers/"
        assert customers_create.method == "POST"
        assert customers_create.operation_id == "customers_create"
        assert customers_create.model_schema is not None

        # Test projects operations
        projects_list = parser.get_operation("projects_list")
        assert projects_list is not None
        assert projects_list.path == "/api/projects/"
        assert projects_list.method == "GET"
        assert projects_list.operation_id == "projects_list"

    def test_get_schema_by_ref(self, parser):
        """Test reference resolution."""
        ref = "#/components/schemas/Customer"
        resolved = parser.get_schema_by_ref(ref)

        assert resolved is not None
        assert resolved["type"] == "object"
        assert "properties" in resolved
        assert "uuid" in resolved["properties"]
        assert "name" in resolved["properties"]

    def test_get_schema_by_ref_invalid(self, parser):
        """Test invalid reference handling."""
        with pytest.raises(ValueError):
            parser.get_schema_by_ref("#/components/schemas/NonExistent")

    def test_get_query_parameters_for_operation(self, parser):
        """Test extracting query parameters for operation."""
        params = parser.get_query_parameters_for_operation("customers_list")

        assert isinstance(params, dict)
        assert "name" in params
        assert "name_exact" in params
        assert "abbreviation" in params
        assert "archived" in params
        assert "backend_id" in params

    def test_get_query_parameters_for_operation_no_params(self, parser):
        """Test operation without query parameters."""
        params = parser.get_query_parameters_for_operation("customers_retrieve")

        assert isinstance(params, dict)
        assert len(params) == 0

    def test_get_operation_nonexistent(self, parser):
        """Test getting non-existent operation."""
        operation = parser.get_operation("nonexistent_operation")
        assert operation is None

    def test_operation_with_request_body(self, parser):
        """Test operation with request body schema."""
        operation = parser.get_operation("customers_create")

        assert operation is not None
        assert operation.model_schema is not None
        assert "type" in operation.model_schema
        assert operation.model_schema["type"] == "object"

    def test_operation_without_request_body(self, parser):
        """Test operation without request body."""
        operation = parser.get_operation("customers_list")

        assert operation is not None
        assert operation.model_schema is None

    def test_empty_spec(self):
        """Test handling of empty API specification."""
        empty_spec = {"openapi": "3.0.0", "paths": {}}
        collector = ValidationErrorCollector()
        parser = ApiSpecParser(empty_spec, collector)

        operation = parser.get_operation("any_operation")
        assert operation is None

    def test_all_http_methods(self):
        """Test support for all HTTP methods."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/api/resource/": {
                    "get": {"operationId": "resource_get"},
                    "post": {"operationId": "resource_post"},
                    "put": {"operationId": "resource_put"},
                    "patch": {"operationId": "resource_patch"},
                    "delete": {"operationId": "resource_delete"},
                }
            },
        }

        collector = ValidationErrorCollector()
        parser = ApiSpecParser(spec, collector)

        assert parser.get_operation("resource_get") is not None
        assert parser.get_operation("resource_post") is not None
        assert parser.get_operation("resource_put") is not None
        assert parser.get_operation("resource_patch") is not None
        assert parser.get_operation("resource_delete") is not None
