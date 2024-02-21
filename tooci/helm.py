import json
import logging
import os

from utils import setup_logging
from utils import shell

log: logging.Logger = setup_logging("tooci")


def helm_repo_to_oci(src_repo, dest, base_oci_ref):
	log.info('to-oci for real')

	# helm repo add capi-operator https://kubernetes-sigs.github.io/cluster-api-operator
	shell(["helm", "repo", "add", dest, f"{src_repo}"])

	# helm repo update dest
	shell(["helm", "repo", "update", dest])

	# list all the available charts, also for devel versions, in JSON format
	all_charts_versions_str = shell(["helm", "search", "repo", dest, "--versions", "--devel", "-o", "json"])
	all_charts_versions = json.loads(all_charts_versions_str)
	log.info(all_charts_versions)

	# loop through all the charts and versions
	for chart_version in all_charts_versions:
		chart_name_full = chart_version["name"]
		chart_name = chart_name_full.split("/")[1]
		chart_helm_version = chart_version["version"]
		chart_app_version = chart_version["app_version"]
		chart_description = chart_version["description"]
		chart_fname = f"{chart_name}-{chart_helm_version}.tgz"
		log.info(
			f"chart_fname: {chart_fname} chart_name_full: {chart_name_full} chart_name: {chart_name} chart_helm_version: {chart_helm_version} chart_app_version: {chart_app_version} chart_description: {chart_description}")

		# If the file already exists in current directory, don't fetch it again
		if os.path.exists(chart_fname):
			log.info(f"Already have {chart_fname} ...")
		else:
			# Now, fetch the chart from the source...
			shell(["helm", "fetch", f"{dest}/{chart_name}", "--version", chart_helm_version])

		if not os.path.exists(chart_fname):
			raise Exception(f"Failed to fetch {chart_fname}")

		# Now, push the chart to the destination...
		shell(["helm", "push", chart_fname, f"oci://{base_oci_ref}/{dest}"])
