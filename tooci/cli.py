import logging
import sys

import click
from rich.pretty import pretty_repr

from helm import Inventory
from utils import setup_logging

log: logging.Logger = setup_logging("cli")


@click.group()
def cli():
	pass


@cli.command(help="Get all charts and all versions from a Helm repo and push them to an OCI registry")
@click.option('--repo-id', envvar="HELM_REPO_ID", help='Id of the the repo in repos.yaml, repositories.<id>', required=True)
@click.option('--base-oci-ref', envvar="BASE_OCI_REF", help='Base OCI reference to push to; do NOT include oci://', required=True)
def process(repo_id, base_oci_ref):
	try:
		log.info(f"to-oci running with id: {repo_id}")
		log.info(f"to-oci running with base_oci_ref: {base_oci_ref}")

		repos = Inventory(base_oci_ref)  # reads repos.yaml
		log.debug(pretty_repr(repos))

		repo = repos.charts[repo_id]
		log.info(f"Processing repo '{repo.repo_id}' at '{repo.source}'")
		log.info(pretty_repr(repo))

		repo.helm_update()
		repo.helm_get_chart_info()

		# So now's the time to process the chartversions, lets do it one by one first, then make it parallel later
		chart_versions = repo.versions_to_process()
		log.info(f"Processing {len(chart_versions)} chart versions")
		log.debug(pretty_repr(chart_versions))

		for chart_version in chart_versions:
			log.info(f"Processing target '{chart_version.oci_target_version}'")
			log.info(pretty_repr(chart_version))
			chart_version.process()
	except:
		log.exception("CLI failed")
		sys.exit(1)


if __name__ == '__main__':
	cli()
