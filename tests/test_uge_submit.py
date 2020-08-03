import os
import subprocess
import pytest

from snakemake_gridengine.uge_submit import Submitter


@pytest.fixture
def jobscript_1():
    jobscript = os.path.join(
        os.path.dirname(__file__),
        "real_jobscript.sh"
    )
    return jobscript


@pytest.fixture
def jobscript_2():
    jobscript = os.path.join(
        os.path.dirname(__file__),
        "real_jobscript_runtime.sh"
    )
    return jobscript


def test_uge_submit_simple():
    jobscript = os.path.join(
        os.path.dirname(__file__),
        "real_jobscript_runtime.sh"
    )
    submitter = Submitter(jobscript)

    assert submitter is not None

    print(submitter.resources_cmd)
    print(submitter.submit_cmd)


def test_ube_submit_submit(jobscript_1, mocker):
    assert jobscript_1 is not None

    subprocess_result = subprocess.CompletedProcess(
        b"", returncode=0,
        stdout=b"Your job 11223344")
    mocker.patch(
        "subprocess.run",return_value=subprocess_result)

    submitter = Submitter(jobscript_1)
    result = submitter.submit()
    print(result)

    subprocess.run.assert_called_once()
