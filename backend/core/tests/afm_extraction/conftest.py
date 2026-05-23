"""
Pytest configuration for AFM extraction tests.
"""

from pathlib import Path

import pytest


@pytest.fixture
def django_folder_of_data(data_for_testing_path) -> Path:
    """
    Returns the path to the folder containing test data for Django.
    """
    return data_for_testing_path / "afm_test_patterns"
