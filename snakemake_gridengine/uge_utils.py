import os

from snakemake import io


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
