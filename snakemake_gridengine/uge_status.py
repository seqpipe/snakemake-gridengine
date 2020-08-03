#!/usr/bin/env python3

import sys
import time
import re
import subprocess
from pathlib import Path
import logging

sys.path.append(str(Path(__file__).parent.absolute()))
from uge_utils import load_cluster_config


logger = logging.getLogger(__name__)


class StatusChecker:
    SUCCESS = "success"
    RUNNING = "running"
    FAILED = "failed"
    STATUS_TABLE = {
        "r": RUNNING,
        "x": RUNNING,
        "t": RUNNING,
        "s": RUNNING,
        "R": RUNNING,
        "qw": RUNNING,
        "d": FAILED,
        "E": FAILED,
        "FAIL": FAILED,
        "EXIT_STATUS: 1": FAILED,
        "SUCCESS": SUCCESS,
        "EXIT_STATUS: 0": SUCCESS,
    }

    """
    From man qstat:
        the  status  of  the  job  -  one  of  d(eletion),  E(rror), h(old),
        r(unning), R(estarted), s(uspended),  S(uspended),  e(N)hanced  sus-
        pended, (P)reempted, t(ransfering), T(hreshold) or w(aiting).

    """

    def __init__(
            self,
            jobid: int,
            outlog: str):
        self._jobid = jobid
        self._outlog = outlog
        self._cluster_config = load_cluster_config("cluster.yaml")

    @property
    def jobid(self) -> int:
        return self._jobid

    @property
    def outlog(self) -> str:
        return self._outlog

    @property
    def max_status_checks(self) -> int:
        return self._cluster_config["__default__"]\
            .get("max_status_checks", 30)

    @property
    def wait_between_tries(self) -> float:
        return self._cluster_config["__default__"]\
            .get("wait_between_tries", 1)

    @property
    def qstat_query_cmd(self) -> str:
        return f"qstat -j {self.jobid}"

    @property
    def qacct_query_cmd(self) -> str:
        return f"qacct -j {self.jobid}"

    @property
    def qdel_cmd(self) -> str:
        return f"qdel -j {self.jobid}"

    def _query_status_using_qstat(self) -> str:
        completed_process = subprocess.run(
            self.qstat_query_cmd,
            check=False, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        if completed_process.returncode != 0:
            error = completed_process.stderr.decode().strip()
            logger.warning(
                f"qstat for {self.jobid} exitted with non zero code: {error}")
            return None

        if not completed_process.stdout:
            logger.warning(
                f"qstat for {self.jobid} exitted with empty stdout")
            return None

        output = completed_process.stdout.decode().strip()
        status = self._qstat_job_state(output)
        logger.debug("qstat job state: %s", status)

        if status not in self.STATUS_TABLE.keys():
            logger.warning(
                f"qstat unknown job status '{status}' for {self.jobid}")
            return None
        return self.STATUS_TABLE[status]

    def _query_status_using_qacct(self) -> str:
        completed_process = subprocess.run(
            self.qacct_query_cmd,
            check=False, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        if completed_process.returncode != 0:
            error = completed_process.stderr.decode().strip()
            logger.warning(
                    f"qacct failed on job {self.jobid} with: {error}")
            return None

        if not completed_process.stdout:
            logger.warning(
                f"qacct failed on job {self.jobid} with empty output")
            return None
        output = completed_process.stdout.decode().strip()
        status = self._qacct_job_state(output)
        if status not in self.STATUS_TABLE.keys():
            logger.warning(
                f"qacct unknown job status '{status}' for {self.jobid}")
            return None
        return self.STATUS_TABLE[status]

    @staticmethod
    def _qstat_job_state(output) -> str:
        state = ""
        for line in output.split("\n"):
            if line.startswith("job_state"):
                state = line.strip()[-2:].strip()
                break  # exit for loop
        return state

    @staticmethod
    def _qacct_job_state(output_stream) -> str:
        exit_state = ""
        failed = ""

        for line in output_stream.split("\n"):
            if line.startswith("failed"):
                failed = line.strip()[-1]
            if line.startswith("exit_status"):
                exit_state = line.strip()[-1]
            if failed != "" and exit_state != "":
                break
        if failed == "0" and exit_state == "0":
            return StatusChecker.SUCCESS
        else:
            return StatusChecker.FAILED

    def get_status(self) -> str:
        status = None
        for _ in range(self.max_status_checks):
            try:
                status = self._query_status_using_qstat()
                if status is not None:
                    return status
                time.sleep(self.wait_between_tries)

                status = self._query_status_using_qacct()
                if status is not None:
                    return status
                time.sleep(self.wait_between_tries)
            except Exception as ex:
                logger.warning("unexpecte exception", ex)

        return status


if __name__ == "__main__":
    jobid = int(sys.argv[1])
    outlog = sys.argv[2]
    status_checker = StatusChecker(jobid, outlog)
    try:
        print(status_checker.get_status())
    except:
        sys.exit(0)
