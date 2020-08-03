#!/usr/bin/env python3

import sys
import time
import re
import subprocess
from pathlib import Path
import logging

from .OSLayer import OSLayer
from .uge_utils import load_cluster_config


logger = logging.getLogger(__name__)


class QstatError(Exception):
    pass


class QacctError(Exception):
    pass


class UnknownStatusLine(Exception):
    pass


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
        outlog: str,
    ):
        self._jobid = jobid
        self._outlog = outlog
        self._cluster_config = load_cluster_config("cluster.yaml")

    def get_log_status_checks(self):
        return self._cluster_config["__default__"]\
            .get("log_status_checks", False)

    def get_wait_between_tries(self):
        return self._cluster_config["__default__"]\
            .get("wait_between_tries", 1)

    def get_max_status_checks(self):
        return self._cluster_config["__default__"]\
            .get("max_status_checks", 30)

    def get_latency_wait(self):
        return self._cluster_config["__default__"]\
            .get("latency_wait", 30)

    @property
    def jobid(self) -> int:
        return self._jobid

    @property
    def outlog(self) -> str:
        return self._outlog

    @property
    def latency_wait(self) -> int:
        return self.get_latency_wait()

    @property
    def max_status_checks(self) -> int:
        return self.get_max_status_checks()

    @property
    def wait_between_tries(self) -> float:
        return self.get_wait_between_tries()

    @property
    def log_status_checks(self) -> bool:
        return self.get_log_status_checks()

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

    def _query_status_using_cluster_log(self) -> str:
        try:
            lastline = OSLayer.tail(self.outlog, num_lines=1)
        except (FileNotFoundError, ValueError):
            return self.STATUS_TABLE["r"]

        status = lastline[0].strip().decode("utf-8")
        if status not in self.STATUS_TABLE.keys():
            raise UnknownStatusLine(
                "Unknown job status '{status}' for {jobid}".format(
                    status=status, jobid=self.jobid)
            )
        return self.STATUS_TABLE[status]

    @staticmethod
    def _extract_time(line, time_name) -> float:
        """ Extracts time elapsed in seconds from usage line for given name
        """
        result = re.search(f"{time_name}=([^,]+)(,|$,\n)", line)
        if not result:
            return 0
        time_str = re.search(f"{time_name}=([^,]+)(,|$,\n)", line).group(1)
        elapsed_time = 0
        multiplier = 1
        multipliers = (1, 60, 60, 24)
        for t, m in zip(reversed(time_str.split(":")), multipliers):
            elapsed_time += multiplier * m * int(t)
            multiplier *= m
        return elapsed_time

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
            return "SUCCESS"
        else:
            return "FAIL"

    def _handle_hung_qstat(self, output_stream) -> str:
        for line in output_stream.split("\n"):
            if line.startswith("usage"):
                wallclock = self._extract_time(line, "wallclock")
                if wallclock < self.cpu_hung_min_time * 60:
                    return False
                cpu = self._extract_time(line, "cpu")
                if (cpu / wallclock) < self.cpu_hung_max_ratio:
                    (
                        returncode,
                        output_stream,
                        error_stream,
                    ) = OSLayer.run_process(self.qdel_cmd)
                    return True
                return False
            return False

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
