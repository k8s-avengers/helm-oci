import logging
import sys

import click

from tooci import helm_repo_to_oci
from utils import setup_logging

log: logging.Logger = setup_logging("cli")


@click.group()
def cli():
	pass


@cli.command(help="Get all charts and all versions from a Helm repo and push them to an OCI registry")
@click.option('--src-repo', envvar="HELM_SRC_REPO", help='The Helm repo to pull charts from', required=True)
@click.option('--dest', envvar="DEST", help='The package name to push to, under base-oci-ref', required=True)
@click.option('--base-oci-ref', envvar="BASE_OCI_REF", help='Base OCI reference to push to; do NOT include oci://', required=True)
def tooci(src_repo, dest, base_oci_ref):
	try:
		log.info(f"to-oci running with src_repo: {src_repo}")
		log.info(f"to-oci running with dest: {dest}")
		log.info(f"to-oci running with base_oci_ref: {base_oci_ref}")
		helm_repo_to_oci(src_repo, dest, base_oci_ref)
	except:
		log.exception("CLI failed")
		sys.exit(1)


if __name__ == '__main__':
	cli()
