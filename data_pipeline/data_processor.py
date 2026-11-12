# src/data_processor.py
import logging
import pandas as pd

logger = logging.getLogger(__name__)

SUPPORTED_AXES = ("rows", "columns")
SUPPORTED_METHODS = ("iqr", "zscore")


def remove_duplicates(df):
    """Remove duplicate rows."""
    rows_before = len(df)
    df = df.drop_duplicates()
    rows_after = len(df)
    logger.debug(
        f"remove_duplicates: {rows_before} -> {rows_after} rows (removed {rows_before - rows_after})"
    )
    return df


def handle_missing(df, axis="rows"):
    """Drop rows or columns containing missing values."""
    if axis not in SUPPORTED_AXES:
        logger.error(f"Unsupported axis for missing values: {axis}")
        raise ValueError(f"Unsupported axis: {axis}")

    if axis == "rows":
        rows_before = len(df)
        df = df.dropna(axis=0)
        logger.debug(
            f"handle_missing: {rows_before} -> {len(df)} rows (removed {rows_before - len(df)})"
        )
    else:
        cols_before = df.shape[1]
        df = df.dropna(axis=1)
        logger.debug(
            f"handle_missing: {cols_before} -> {df.shape[1]} columns (removed {cols_before - df.shape[1]})"
        )
    return df


def remove_outliers(df, columns, method, threshold):
    """Remove outliers from the specified numeric columns."""
    if method not in SUPPORTED_METHODS:
        logger.error(f"Unsupported outlier method: {method}")
        raise ValueError(f"Unsupported outlier method: {method}")

    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        logger.error(f"Invalid outlier threshold: {threshold}")
        raise ValueError(f"Invalid outlier threshold: {threshold}")

    for col in columns:
        if col not in df.columns:
            logger.warning(f"Column not found: {col}")
            continue
        if not pd.api.types.is_numeric_dtype(df[col]):
            logger.warning(f"Column is not numeric: {col}")
            continue

        rows_before = len(df)
        values = df[col]

        if method == "iqr":
            q1 = values.quantile(0.25)
            q3 = values.quantile(0.75)
            iqr = q3 - q1
            lower = q1 - threshold * iqr
            upper = q3 + threshold * iqr
            keep = values.between(lower, upper)
        else:  # zscore
            std = values.std()
            if pd.isna(std) or std == 0:
                keep = pd.Series(True, index=df.index)
            else:
                z = (values - values.mean()) / std
                keep = z.abs() <= threshold

        # Missing values are not outliers; leave them for handle_missing().
        df = df[keep | values.isna()]

        logger.debug(
            f"{col}: method={method}, threshold={threshold}, removed={rows_before - len(df)}"
        )
    return df


def process_data(df, config):
    """Apply the processing steps enabled in the configuration."""
    processing = (config or {}).get("processing", {}) or {}

    if processing.get("remove_duplicates", False):
        df = remove_duplicates(df)

    missing = processing.get("missing", {}) or {}
    if missing.get("enabled", False):
        df = handle_missing(df, axis=missing.get("axis", "rows"))

    outliers = processing.get("outliers", {}) or {}
    if outliers.get("enabled", False):
        df = remove_outliers(
            df,
            columns=outliers.get("columns", []) or [],
            method=outliers.get("method"),
            threshold=outliers.get("threshold"),
        )

    return df


def create_cleaning_report(df_before, df_after):
    """Return a dictionary summarizing the cleaning results."""
    rows_before, columns_before = df_before.shape
    rows_after, columns_after = df_after.shape
    return {
        "rows_before": rows_before,
        "rows_after": rows_after,
        "rows_removed": rows_before - rows_after,
        "columns_before": columns_before,
        "columns_after": columns_after,
        "columns_removed": columns_before - columns_after,
    }
