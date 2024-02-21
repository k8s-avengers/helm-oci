import concurrent.futures
import json
import logging
import multiprocessing
import sys

import click
from rich.pretty import pretty_repr

import utils
from helm import Inventory
from utils import setup_logging

log: logging.Logger = setup_logging("cli")


@click.group()
def cli():
	pass


@cli.command(help="Produce GHA matrix from the inventory of repos")
def gha_matrix():
	repos = Inventory(None)
	contents = [{"id": chart.repo_id} for chart in repos.charts.values()]
	utils.set_gha_output("jsonmatrix", json.dumps(contents))


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

		# Use a parallel pool to process the chart versions, use double the number of cpu cores, but not more than 16
		max_workers = 16 if ((multiprocessing.cpu_count() * 2) > 16) else (multiprocessing.cpu_count() * 2)
		log.info(f"Using {max_workers} workers for parallel processing.")
		with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
			def in_process(cv):
				log.info(f"Processing target '{cv.oci_target_version}'")
				log.info(pretty_repr(cv))
				ret = cv.process()
				log.info(f"Processed target '{cv.oci_target_version}' OK")
				return ret

			results = list(executor.map(in_process, chart_versions))

		new_versions = len([x for x in results if x])
		log.info(f"Finished processing {len(chart_versions)} chart versions; {new_versions} new versions were processed")

	except:
		log.exception("CLI failed")
		sys.exit(1)


if __name__ == '__main__':
	cli()
