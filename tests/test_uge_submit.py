import os
import subprocess
import pytest

from snakemake_gridengine.uge_submit import Submitter
from snakemake_gridengine.uge_status import StatusChecker


import logging
import sys

root = logging.getLogger()
root.setLevel(logging.DEBUG)

handler = logging.StreamHandler(sys.stderr)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
root.addHandler(handler)


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
        stdout=b"""Your job 1504976 ("test_qstat.sh") has been submitted""")
    mocker.patch(
        "subprocess.run",return_value=subprocess_result)

    submitter = Submitter(jobscript_1)
    result = submitter.submit()
    print(result)

    subprocess.run.assert_called_once()


def test_uge_qstat_status_non_zero_simple(mocker):
    qstat_not_found_stderr = \
        b"""Following jobs do not exist or permissions are not sufficient: 
1504976"""

    checker = StatusChecker(
        1504976,
        "cluster_logs/search_fasta_on_index/smk.search_fasta_on_index.i=0.out"
    )

    subprocess_result = subprocess.CompletedProcess(
        b"", returncode=1,
        stdout=b"",
        stderr=qstat_not_found_stderr)
    mocker.patch(
        "subprocess.run",return_value=subprocess_result)
    
    result = checker._query_status_using_qstat()
    print(result)

    subprocess.run.assert_called_once()
    assert result is None

def test_uge_qstat_status_zero_simple(mocker):
    filename = os.path.join(
        os.path.dirname(__file__),
        "qstat.txt"
    )

    with open(filename, "rb") as infile:
        content = infile.read()

    subprocess_result = subprocess.CompletedProcess(
        b"", returncode=0,
        stdout=content,
        stderr=b"")
    mocker.patch(
        "subprocess.run",return_value=subprocess_result)

    checker = StatusChecker(
        1504976,
        "cluster_logs/search_fasta_on_index/smk.search_fasta_on_index.i=0.out"
    )
    
    result = checker._query_status_using_qstat()
    print(result)

    subprocess.run.assert_called_once()
    assert result == "running"
    assert result == StatusChecker.RUNNING


def test_uge_qacct_status_zero_simple(mocker):
    filename = os.path.join(
        os.path.dirname(__file__),
        "qacct.txt"
    )

    with open(filename, "rb") as infile:
        content = infile.read()

    subprocess_result = subprocess.CompletedProcess(
        b"", returncode=0,
        stdout=content,
        stderr=b"")
    mocker.patch(
        "subprocess.run",return_value=subprocess_result)

    checker = StatusChecker(
        1504976,
        "cluster_logs/search_fasta_on_index/smk.search_fasta_on_index.i=0.out"
    )
    
    result = checker._query_status_using_qacct()
    print(result)

    subprocess.run.assert_called_once()

    assert result == "success"
    assert result == StatusChecker.SUCCESS

def test_uge_qacct_status_non_zero_simple(mocker):
    qacct_not_found_stderr = b"error: job id 1504976 not found"

    subprocess_result = subprocess.CompletedProcess(
        b"", returncode=1,
        stdout=b"",
        stderr=qacct_not_found_stderr)
    mocker.patch(
        "subprocess.run",return_value=subprocess_result)

    checker = StatusChecker(
        1504976,
        "cluster_logs/search_fasta_on_index/smk.search_fasta_on_index.i=0.out"
    )
    
    result = checker._query_status_using_qacct()
    print(result)

    subprocess.run.assert_called_once()

    assert result is None

