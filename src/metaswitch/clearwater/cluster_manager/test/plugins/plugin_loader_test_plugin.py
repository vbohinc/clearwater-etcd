# Copyright (C) Metaswitch Networks
# If license terms are provided to you in a COPYING file in the root directory
# of the source code repository by which you are accessing this code, then
# the license outlined in that COPYING file applies to your use.
# Otherwise no rights are granted except for those provided to you by
# Metaswitch Networks in a separate written agreement.



from metaswitch.clearwater.cluster_manager.plugin_base import SynchroniserPluginBase
import logging

_log = logging.getLogger("example_plugin")


class PluginLoaderTestPlugin(SynchroniserPluginBase):
    def __init__(self, params):
        pass

    def key(self):
        return "/test"

    def on_cluster_changing(self, cluster_view):
        _log.debug("New view of the cluster is {}".format(cluster_view))

    def on_joining_cluster(self, cluster_view):
        _log.info("I'm about to join the cluster")

    def on_new_cluster_config_ready(self, cluster_view):
        _log.info("All nodes have updated configuration")

    def on_stable_cluster(self, cluster_view):
        _log.info("Cluster is stable")
        _log.debug("Clearing not-clustered alarm")

    def on_leaving_cluster(self, cluster_view):
        _log.info("I'm out of the cluster")

def load_as_plugin(params):
    return PluginLoaderTestPlugin(params)
