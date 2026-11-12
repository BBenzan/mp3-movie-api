import logging
import sqlite3

import pandas as pd

from .database import get_connection, initialize_database

logger = logging.getLogger(__name__)
MOVIE_COLUMNS = ["title", "release_year", "rating", "genre"]


class MovieStorage:
    def __init__(self, db_path="data/movies.db"):
        self.db_path = db_path
        initialize_database(self.db_path)

    def save(self, df):
        """Replace all movie rows in one transaction."""
        # Align to the table's four columns. A column dropped during
        # processing (missing axis="columns") is stored as NULL.
        movies = df.reindex(columns=MOVIE_COLUMNS)
        # astype(object) turns NumPy values into Python int/float/str, which
        # sqlite3 can bind; where() turns NaN and other missing values into None (SQL NULL).
        movies = movies.astype(object).where(movies.notna(), None)
        rows = list(movies.itertuples(index=False, name=None))

        connection = get_connection(self.db_path)
        try:
            # sqlite3 opens a transaction at the DELETE, so the DELETE and all
            # INSERTs commit together or not at all.
            connection.execute("DELETE FROM movies")
            connection.executemany(
                "INSERT INTO movies (title, release_year, rating, genre) "
                "VALUES (?, ?, ?, ?)",
                rows,
            )
            connection.commit()
        except sqlite3.Error as error:
            connection.rollback()
            logger.error(f"Failed to store movies, rolled back: {error}")
            raise
        finally:
            connection.close()

        logger.debug(f"Stored movies in SQLite: rows={len(rows)}")

    def get(self):
        """Return the four movie columns as a DataFrame, ordered by id."""
        connection = get_connection(self.db_path)
        try:
            rows = connection.execute(
                "SELECT title, release_year, rating, genre FROM movies ORDER BY id"
            ).fetchall()
        finally:
            connection.close()

        df = pd.DataFrame([tuple(row) for row in rows], columns=MOVIE_COLUMNS)
        logger.debug(f"Loaded movies from SQLite: rows={len(df)}")
        return df

    def select_columns(self, columns, limit=5):
        """Return id plus the requested movie columns, ordered by id."""
        if not columns:
            logger.error("Select at least one column")
            raise ValueError("Select at least one column")

        for column in columns:
            if column not in MOVIE_COLUMNS:
                logger.error(f"Unsupported column: {column}")
                raise ValueError(f"Unsupported column: {column}")

        selected_columns = ", ".join(["id"] + columns)
        connection = get_connection(self.db_path)
        try:
            rows = connection.execute(
                f"SELECT {selected_columns} FROM movies ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
            results = [dict(row) for row in rows]
            logger.debug(f"Selected movies: columns={columns}, rows={len(results)}")
            return results
        finally:
            connection.close()

    def count_movies(self):
        """Return the number of stored movies using SQL COUNT(*)."""
        connection = get_connection(self.db_path)
        try:
            return connection.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
        finally:
            connection.close()

    def query_movies(self, columns, min_rating, limit):
        """Return selected fields from matching movies using SQL."""
        if not columns:
            logger.error("Select at least one column")
            raise ValueError("Select at least one column")

        for column in columns:
            if column not in MOVIE_COLUMNS:
                logger.error(f"Unsupported column: {column}")
                raise ValueError(f"Unsupported column: {column}")

        selected_columns = ", ".join(["id"] + columns)
        connection = get_connection(self.db_path)
        try:
            rows = connection.execute(
                f"SELECT {selected_columns} FROM movies "
                "WHERE rating >= ? "
                "ORDER BY rating DESC, id ASC "
                "LIMIT ?",
                (min_rating, limit),
            ).fetchall()
            results = [dict(row) for row in rows]
            logger.debug(f"Queried movies: columns={columns}, rows={len(results)}")
            return results
        finally:
            connection.close()
