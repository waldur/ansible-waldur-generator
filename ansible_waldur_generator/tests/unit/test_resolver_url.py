from unittest.mock import Mock
from ansible_waldur_generator.interfaces.resolver import ParameterResolver


class TestParameterResolverUrlSupport:
    """Test that ParameterResolver handles URL inputs correctly."""

    def test_resolve_to_url_with_url_input(self):
        """Test that resolve_to_url returns the URL directly without API calls."""
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

        resolver = ParameterResolver(mock_runner)
        input_url = "http://127.0.0.1:8000/api/projects/project-123/"

        # Act
        result = resolver.resolve_to_url("project", input_url)

        # Assert
        assert result == input_url
        mock_runner.send_request.assert_not_called()

    def test_resolve_single_value_with_url_input(self):
        """Test that _resolve_single_value fetches the resource when a URL is provided."""
        # This is for recursive resolution (e.g. within a dict or list)
        # Arrange
        mock_runner = Mock()
        mock_runner.module = Mock()
        mock_runner.module.params = {}
        mock_runner.context = {
            "resolvers": {
                "project": {
                    "url": "/api/projects/",
                    "error_message": "Project '{value}' not found",
                }
            }
        }
        mock_runner._is_uuid = Mock(return_value=False)
        mock_runner.send_request = Mock(
            return_value=(
                {
                    "uuid": "project-123",
                    "url": "http://127.0.0.1:8000/api/projects/project-123/",
                },
                200,
            )
        )
        resolver = ParameterResolver(mock_runner)
        resolver._build_dependency_filters = Mock(return_value={})

        input_url = "http://127.0.0.1:8000/api/projects/project-123/"
        resolver_conf = mock_runner.context["resolvers"]["project"]

        # Act
        result = resolver._resolve_single_value("project", input_url, resolver_conf)

        # Assert
        assert result == input_url
        mock_runner.send_request.assert_called_once_with("GET", input_url)
        # Ensure it was cached
        assert ("project", input_url) in resolver.cache
