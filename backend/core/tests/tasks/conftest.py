import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tasks_modules_data_path(data_for_testing_path) -> Path:
    return data_for_testing_path / "for_tasks"


@pytest.fixture
def tasks_modules_data_temp_path(tasks_modules_data_path):
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)
        shutil.copytree(tasks_modules_data_path, temp_dir, dirs_exist_ok=True)
        yield temp_dir


@pytest.fixture
def a_pickle_to_store(tasks_modules_data_temp_path) -> Path:
    pkl_path = tasks_modules_data_temp_path / "chunk_2025-09-19_1_225009.pkl"
    pkl_path = tasks_modules_data_temp_path / "chunk_of_two_decisions.pkl"

    return pkl_path
