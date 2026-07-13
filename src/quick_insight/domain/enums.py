from __future__ import annotations

from enum import StrEnum


class DatasetKind(StrEnum):
    TABULAR = "tabular"
    TEXT_CORPUS = "text_corpus"


class AnalysisIntent(StrEnum):
    AUTO = "auto"
    TREND = "trend"
    COMPARISON = "comparison"
    DISTRIBUTION = "distribution"
    RELATIONSHIP = "relationship"
    COMPOSITION = "composition"
    ANOMALY = "anomaly"
    CORRELATION = "correlation"


class ColumnSemanticType(StrEnum):
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    TEXT = "text"
    LONG_TEXT = "long_text"
    IDENTIFIER = "identifier"
    GEO_LATITUDE = "geo_latitude"
    GEO_LONGITUDE = "geo_longitude"
    PRIMARY_CATEGORY = "primary_category"
    TAG_LIST = "tag_list"
    SOURCE_REFERENCE = "source_reference"
    UNKNOWN = "unknown"
