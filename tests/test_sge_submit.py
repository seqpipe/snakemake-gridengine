import os

from snakemake_gridengine.sge_submit import parse_jobscript, \
    read_job_properties


def test_parse_jobscript():
    argv=["real_jobscript.sh"]

    result = parse_jobscript(argv)
    assert result == argv[0]


def test_read_job_properties():
    filename = os.path.join(
        os.path.dirname(__file__),
        "real_jobscript.sh"
    )
    assert os.path.exists(filename)
    result = read_job_properties(filename)
    assert result is not None
    from pprint import pprint
    pprint(result)
