# src/data_validator.py
import logging
import pandas as pd


logger = logging.getLogger(__name__)


def validate_dataframe(df, required_columns, numeric_columns):
    """Validate the DataFrame and return valid data.

    required_columns: a list of column names that must exist.
    numeric_columns: a list of column names whose values should be numeric.
    """
    df = df.copy()
    rows_before = len(df)

    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        logger.error(f"Missing required column(s): {', '.join(missing_columns)}")
        raise ValueError(f"Missing required column(s): {missing_columns}")

    for col in numeric_columns:
        if col not in df.columns:
            logger.error(f"Numeric column not found: {col}")
            raise ValueError(f"Numeric column not found: {col}")

        invalid_rows = []
        for i, value in df[col].items():
            if pd.notna(value):
                try:
                    float(value)
                except ValueError:
                    logger.warning(
                        f"Invalid numeric value in {col} at row {i}: {value}"
                    )
                    invalid_rows.append(i)

        if invalid_rows:
            df = df.drop(index=invalid_rows)
            logger.warning(
                f"Removed {len(invalid_rows)} rows with invalid numeric values in {col}"
            )

        # convert to a numeric data type
        df[col] = pd.to_numeric(df[col])

    rows_after = len(df)
    logger.debug(
        f"Validation: {rows_before} -> {rows_after} rows (valid={rows_after}, removed={rows_before - rows_after})"
    )
    return df
