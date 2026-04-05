"""
Test 2: Configuration Schema Validation

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
    "sync_timeout",
    "recommend_count",
    "min_rating",
    "request_interval_min",
    "request_interval_max",
    "max_retries",
    "detail_enrich_limit",
}

# Mapping from schema type string to Python type for default validation
TYPE_MAP = {
    "int": int,
    "float": (int, float),  # accept int where float is expected (e.g., default: 60 is valid for float)
    "string": str,
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

    def test_every_field_has_default(self, schema):
        for key, field in schema.items():
            assert "default" in field, f"Field '{key}' missing 'default'"

    def test_type_values_are_valid(self, schema):
        """All declared types are in the allowed set."""
        valid_types = {"int", "float", "string", "bool"}
        for key, field in schema.items():
            assert field["type"] in valid_types, (
                f"Field '{key}' has invalid type '{field['type']}'"
            )

    def test_default_types_match_declared_types(self, schema):
        """Default value type must match the declared 'type' field."""
        for key, field in schema.items():
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
                assert isinstance(field["hint"], str), (
                    f"Field '{key}' hint is not a string"
                )
                assert len(field["hint"]) > 0, f"Field '{key}' has empty hint"

    def test_no_extra_keys_per_field(self, schema):
        """Each field should only have known keys: type, description, hint, default."""
        allowed_keys = {"type", "description", "hint", "default"}
        for key, field in schema.items():
            extra = set(field.keys()) - allowed_keys
            assert not extra, f"Field '{key}' has unknown keys: {extra}"


class TestConfSchemaSemanticConstraints:
    """Validate semantic correctness of default values."""

    def test_sync_timeout_positive(self, schema):
        assert schema["sync_timeout"]["default"] > 0

    def test_recommend_count_in_range(self, schema):
        val = schema["recommend_count"]["default"]
        assert 1 <= val <= 50, f"recommend_count default {val} out of reasonable range"

    def test_min_rating_in_range(self, schema):
        val = schema["min_rating"]["default"]
        assert 0.0 <= val <= 10.0, f"min_rating default {val} out of 0-10 range"

    def test_request_interval_min_less_than_max(self, schema):
        min_val = schema["request_interval_min"]["default"]
        max_val = schema["request_interval_max"]["default"]
        assert min_val <= max_val, (
            f"request_interval_min ({min_val}) > request_interval_max ({max_val})"
        )

    def test_request_intervals_non_negative(self, schema):
        assert schema["request_interval_min"]["default"] >= 0
        assert schema["request_interval_max"]["default"] >= 0

    def test_max_retries_positive(self, schema):
        assert schema["max_retries"]["default"] > 0

    def test_detail_enrich_limit_positive(self, schema):
        assert schema["detail_enrich_limit"]["default"] > 0
