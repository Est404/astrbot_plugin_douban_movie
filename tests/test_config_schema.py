"""
Test: Configuration Schema Validation

Verifies that _conf_schema.json:
- Is valid JSON
- Has required fields (type, description, default) on every config item
- Has default value types that match the declared type
- Contains all expected configuration keys
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def schema(plugin_dir):
    """Load and parse _conf_schema.json."""
    path = plugin_dir / "_conf_schema.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


EXPECTED_FIELDS = {
    "douban_cookie",
    "recommend_count",
    "candidate_pool_size",
    "min_rating",
    "request_interval_min",
    "request_interval_max",
    "max_retries",
    "profile_provider_id",
    "recommend_provider_id",
}

# Mapping from schema type string to Python type for default validation
TYPE_MAP = {
    "int": int,
    "float": (int, float),  # accept int where float is expected
    "string": str,
    "text": str,
    "bool": bool,
}


class TestConfSchemaStructure:
    """Validate _conf_schema.json structure and completeness."""

    def test_schema_is_valid_json(self, plugin_dir):
        """The file parses as valid JSON."""
        path = plugin_dir / "_conf_schema.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_schema_contains_all_expected_fields(self, schema):
        """All expected configuration keys are present."""
        missing = EXPECTED_FIELDS - set(schema.keys())
        assert not missing, f"Missing fields: {missing}"

    def test_schema_has_no_extra_fields(self, schema):
        """No unexpected configuration keys are present."""
        extra = set(schema.keys()) - EXPECTED_FIELDS
        assert not extra, f"Unexpected fields: {extra}"

    def test_schema_is_non_empty(self, schema):
        """Schema is not an empty object."""
        assert len(schema) > 0


class TestConfSchemaFieldConstraints:
    """Validate each field has proper structure."""

    def test_every_field_has_type(self, schema):
        for key, field in schema.items():
            assert "type" in field, f"Field '{key}' missing 'type'"

    def test_every_field_has_description(self, schema):
        for key, field in schema.items():
            assert "description" in field, f"Field '{key}' missing 'description'"
            assert len(field["description"]) > 0, f"Field '{key}' has empty description"

    def test_every_field_has_default_or_is_provider_select(self, schema):
        """Fields should have 'default', unless they are provider selectors."""
        for key, field in schema.items():
            if field.get("_special") == "select_provider":
                continue
            assert "default" in field, f"Field '{key}' missing 'default'"

    def test_type_values_are_valid(self, schema):
        """All declared types are in the allowed set."""
        valid_types = {"int", "float", "string", "text", "bool"}
        for key, field in schema.items():
            assert field["type"] in valid_types, (
                f"Field '{key}' has invalid type '{field['type']}'"
            )

    def test_default_types_match_declared_types(self, schema):
        """Default value type must match the declared 'type' field."""
        for key, field in schema.items():
            if "default" not in field:
                continue
            declared = field["type"]
            default = field["default"]
            expected_type = TYPE_MAP[declared]
            assert isinstance(default, expected_type), (
                f"Field '{key}': declared type '{declared}' but default "
                f"{default!r} is {type(default).__name__}"
            )

    def test_hint_field_is_string_when_present(self, schema):
        """If 'hint' is present, it must be a non-empty string."""
        for key, field in schema.items():
            if "hint" in field:
                assert isinstance(field["hint"], str)
                assert len(field["hint"]) > 0, f"Field '{key}' has empty hint"

    def test_no_extra_keys_per_field(self, schema):
        """Each field should only have known keys."""
        allowed_keys = {"type", "description", "hint", "default", "_special"}
        for key, field in schema.items():
            extra = set(field.keys()) - allowed_keys
            assert not extra, f"Field '{key}' has unknown keys: {extra}"


class TestConfSchemaSemanticConstraints:
    """Validate semantic correctness of default values."""

    def test_recommend_count_in_range(self, schema):
        val = schema["recommend_count"]["default"]
        assert 1 <= val <= 50

    def test_candidate_pool_size_positive(self, schema):
        assert schema["candidate_pool_size"]["default"] > 0

    def test_min_rating_in_range(self, schema):
        val = schema["min_rating"]["default"]
        assert 0.0 <= val <= 10.0

    def test_min_rating_default_is_7(self, schema):
        assert schema["min_rating"]["default"] == 7.0

    def test_request_interval_min_less_than_max(self, schema):
        min_val = schema["request_interval_min"]["default"]
        max_val = schema["request_interval_max"]["default"]
        assert min_val <= max_val

    def test_request_intervals_non_negative(self, schema):
        assert schema["request_interval_min"]["default"] >= 0
        assert schema["request_interval_max"]["default"] >= 0

    def test_max_retries_positive(self, schema):
        assert schema["max_retries"]["default"] > 0

    def test_douban_cookie_default_empty(self, schema):
        assert schema["douban_cookie"]["default"] == ""


class TestConfSchemaProviderFields:
    """Validate the LLM provider configuration fields."""

    def test_profile_provider_id_exists(self, schema):
        assert "profile_provider_id" in schema

    def test_recommend_provider_id_exists(self, schema):
        assert "recommend_provider_id" in schema

    def test_provider_fields_are_string_type(self, schema):
        for key in ("profile_provider_id", "recommend_provider_id"):
            assert schema[key]["type"] == "string"

    def test_provider_fields_have_special_marker(self, schema):
        for key in ("profile_provider_id", "recommend_provider_id"):
            assert schema[key].get("_special") == "select_provider"

    def test_provider_fields_have_description(self, schema):
        for key in ("profile_provider_id", "recommend_provider_id"):
            assert "description" in schema[key]
            assert len(schema[key]["description"]) > 0

    def test_provider_fields_have_hint(self, schema):
        for key in ("profile_provider_id", "recommend_provider_id"):
            assert "hint" in schema[key]
            assert isinstance(schema[key]["hint"], str)
            assert len(schema[key]["hint"]) > 0
