#!/usr/bin/env python3
import os
import math
import re
import subprocess
import sys
import shutil
from pathlib import Path
from typing import List, Union, Optional

from snakemake.utils import read_job_properties
from snakemake import io

from .OSLayer import OSLayer
from .uge_config import Config
from .memory_units import Unit, Memory

PathLike = Union[str, Path]


def load_cluster_config(path=None):
    """\
    Load config to dict either from absolute path or relative to profile dir.\
    """
    if path:
        path = os.path.join(
            os.path.dirname(__file__), os.path.expandvars(path))
        default_cluster_config = io.load_configfile(path)
    else:
        default_cluster_config = {}
    if "__default__" not in default_cluster_config:
        default_cluster_config["__default__"] = {}
    return default_cluster_config


class QsubInvocationError(Exception):
    pass

class JobidNotFoundError(Exception):
    pass

class Submitter:
    def __init__(
            self,
            jobscript: PathLike,
            cluster_cmds: List[str] = None,
            memory_units: Unit = Unit.GIGA,
            uge_config: Optional[Config] = None):

        if cluster_cmds is None:
            cluster_cmds = []
        if uge_config is None:
            uge_config = Config()

        self._jobscript = jobscript
        self._cluster_cmd = " ".join(cluster_cmds)
        self._memory_units = memory_units
        self._job_properties = read_job_properties(self._jobscript)
        self.uge_config = uge_config
        self._cluster_config = load_cluster_config("cluster.yaml")

    def get_default_mem_mb(self):
        return self._cluster_config["__default__"].get("default_mem_mb", 1024)

    def get_default_threads(self):
        return self._cluster_config["__default__"].get("default_threads", 1)

    def get_log_dir(self):
        return self._cluster_config["__default__"]\
            .get("log_dir", "cluster_logs")

    def get_default_queue(self):
        return self._cluster_config["__default__"]\
            .get("default_queue", "")

    @property
    def jobscript(self) -> str:
        return self._jobscript

    @property
    def job_properties(self) -> dict:
        return self._job_properties

    @property
    def cluster(self) -> dict:
        return self.job_properties.get("cluster", dict())

    @property
    def threads(self) -> int:
        return self.job_properties.get("threads",
                self.get_default_threads())

    @property
    def resources(self) -> dict:
        return self.job_properties.get("resources", dict())

    @property
    def mem_mb(self) -> Memory:
        mem_value = self.resources.get(
            "mem_mb", self.cluster.get("mem_mb",
                self.get_default_mem_mb())
        )
        return Memory(mem_value, unit=Unit.MEGA)

    @property
    def memory_units(self) -> Unit:
        return self._memory_units

    @property
    def runtime(self) -> int:
        rt = self.cluster.get("runtime", None)
        if rt:
            rt = int(rt)
        return rt

    @property
    def resources_cmd(self) -> str:
        mem_in_cluster_units = self.mem_mb.to(self.memory_units)
        res_cmd = []
        if self.threads > 1:
            res_cmd.append(f"-pe smp {self.threads}")
            per_thread = round(mem_in_cluster_units.value / self.threads, 2)
        else:
            per_thread = math.ceil(mem_in_cluster_units.value)
        res_cmd.append(f"-l h_vmem={per_thread}G")
        res_cmd.append(f"-l m_mem_free={per_thread}G")

        if self.runtime:
            hours = self.runtime // 60
            mins = self.runtime % 60
            res_cmd.append(f"-l h_rt={hours}:{mins}:00")
        return " ".join(res_cmd)

    @property
    def wildcards(self) -> dict:
        return self.job_properties.get("wildcards", dict())

    @property
    def wildcards_str(self) -> str:
        return (
            ".".join("{}={}".format(k, v) for k, v in self.wildcards.items())
            or "unique"
        )

    @property
    def rule_name(self) -> str:
        if not self.is_group_jobtype:
            return self.job_properties.get("rule", "rule_name")
        return self.groupid

    @property
    def groupid(self) -> str:
        return self.job_properties.get("groupid", "group")

    @property
    def is_group_jobtype(self) -> bool:
        return self.job_properties.get("type", "") == "group"

    @property
    def jobname(self) -> str:
        if self.is_group_jobtype:
            return "{groupid}_{jobid}".format(groupid=self.groupid,
                    jobid=self.jobid)
        return self.cluster.get(
            "jobname",
            "smk.{rule_name}.{wildcards_str}".format(
                rule_name=self.rule_name, wildcards_str=self.wildcards_str
            ),
        )

    @property
    def jobid(self) -> str:
        if self.is_group_jobtype:
            return self.job_properties.get("jobid", "").split("-")[0]
        return str(self.job_properties.get("jobid"))

    @property
    def logdir(self) -> Path:
        project_logdir = Path(self.cluster.get("logdir",
            self.get_log_dir()))
        return project_logdir / self.rule_name

    @property
    def outlog(self) -> Path:
        if self.is_group_jobtype:
            return self.logdir / "groupid{groupid}_jobid{jobid}.out".format(
                groupid=self.groupid, jobid=self.jobid)
        return self.logdir / "{jobname}.out".format(jobname=self.jobname)

    @property
    def errlog(self) -> Path:
        if self.is_group_jobtype:
            return self.logdir / "groupid{groupid}_jobid{jobid}.err".format(
                groupid=self.groupid, jobid=self.jobid)
        return self.logdir / "{jobname}.err".format(jobname=self.jobname)

    @property
    def jobinfo_cmd(self) -> str:
        return '-o "{out_log}" -e "{err_log}" -N "{jobname}"'.format(
            out_log=self.outlog, err_log=self.errlog, jobname=self.jobname
        )

    @property
    def queue(self) -> str:
        return self.cluster.get("queue", self.get_default_queue())

    @property
    def queue_cmd(self) -> str:
        return "-q {}".format(self.queue) if self.queue else ""

    @property
    def rule_specific_params(self) -> str:
        return self.uge_config.params_for_rule(self.rule_name)

    @property
    def cluster_cmd(self) -> str:
        return self._cluster_cmd

    @property
    def submit_cmd(self) -> str:
        params = [
            "qsub -cwd -V",
            self.resources_cmd,
            self.jobinfo_cmd,
            self.queue_cmd,
            self.cluster_cmd,
            self.rule_specific_params,
            self.jobscript,
        ]
        return " ".join(p for p in params if p)

    def _create_logdir(self):
        os.makedirs(self.logdir, exist_ok=True)

    def _remove_previous_logs(self):
        if os.path.exists(self.outlog):
            assert os.path.isfile(self.outlog)
            os.remove(self.outlog)
        
        if os.path.exists(self.errlog):
            assert os.path.isfile(self.errlog)
            os.remove(self.errlog)

    def submit(self):
        self._create_logdir()
        self._remove_previous_logs()
        try:
            completed_process = subprocess.run(
                self.submit_cmd,
                check=False, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            assert completed_process.returncode == 0
            output = completed_process.stdout.decode().strip()
            match = re.search(r"Your job (\d+).*", output)
            jobid = match.group(1)
            jobid = int(jobid)

            return f"{jobid} {self.outlog}"
        except subprocess.CalledProcessError as error:
            raise QsubInvocationError(error)
        except AttributeError as error:
            raise JobidNotFoundError(error)

        return None

if __name__ == "__main__":
    workdir = Path().resolve()
    config_file = workdir / "uge.yaml"
    if config_file.exists():
        with config_file.open() as stream:
            uge_config = Config.from_stream(stream)
    else:
        uge_config = Config()

    jobscript = sys.argv[-1]
    cluster_cmds = sys.argv[1:-1]
    uge_submit = Submitter(
        jobscript=jobscript,
        uge_config=uge_config,
        cluster_cmds=cluster_cmds,
    )
    result = uge_submit.submit()
    assert result is not None

    print(result)
