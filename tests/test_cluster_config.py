from snakemake_gridengine.sge_submit import load_cluster_config


def test_load_cluster_config_simple():
    res = load_cluster_config("cluster.yaml")
    assert res is not None
    print(res)
