[![pypi](https://img.shields.io/pypi/v/fink-client.svg)](https://pypi.python.org/pypi/fink-client)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=fink-client&metric=alert_status)](https://sonarcloud.io/dashboard?id=fink-client)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=fink-client&metric=sqale_rating)](https://sonarcloud.io/dashboard?id=fink-client)
[![Sentinel](https://github.com/astrolabsoftware/fink-client/workflows/Sentinel/badge.svg)](https://github.com/astrolabsoftware/fink-client/actions?query=workflow%3ASentinel)
[![codecov](https://codecov.io/gh/astrolabsoftware/fink-client/branch/master/graph/badge.svg)](https://codecov.io/gh/astrolabsoftware/fink-client)
[![Documentation Status](https://readthedocs.org/projects/fink-broker/badge/?version=latest)](https://fink-broker.readthedocs.io/en/latest/?badge=latest)

# Fink client

`fink-client` is a light package to manipulate catalogs and alerts issued from the [fink broker](https://github.com/astrolabsoftware/fink-broker) programmatically. It is used in the context of 2 major Fink services: Livestream and Data Transfer.

## Installation

`fink_client` requires a version of Python 3.9+.

### Install with pip

```bash
pip install fink-client --upgrade
```

### Use or develop in a controlled environment

```bash
git clone https://github.com/astrolabsoftware/fink-client.git
cd fink-client
conda env create -f environment.yml
conda activate fink-client
```

and then install it locally:

```bash
# install for development
pip install -e .
```

## Registration

In order to connect and poll alerts from Fink, you need to get your credentials:

1. Subscribe to one or more Fink streams by filling this [form](https://forms.gle/2td4jysT4e9pkf889).
2. After filling the form, we will send your credentials. Register them on your laptop by simply running:
  ```
  fink_client_register -username <USERNAME> -group_id <GROUP_ID> ...
  ```

## Livestream usage

Once you have your credentials, you are ready to poll streams!

```bash
fink_consumer -h
usage: fink_consumer [-h] [--display] [-limit LIMIT] [--available_topics]
                     [--save] [-outdir OUTDIR] [-schema SCHEMA]

Kafka consumer to listen and archive Fink streams from the Livestream service

optional arguments:
  -h, --help          show this help message and exit
  --display           If specified, print on screen information about incoming
                      alert.
  -limit LIMIT        If specified, download only `limit` alerts. Default is
                      None.
  --available_topics  If specified, print on screen information about
                      available topics.
  --save              If specified, save alert data on disk (Avro). See also
                      -outdir.
  -outdir OUTDIR      Folder to store incoming alerts if --save is set. It
                      must exist.
  -schema SCHEMA      Avro schema to decode the incoming alerts. Default is
                      None (latest version downloaded from server)
```

You can also look at an alert on the disk:

```bash
fink_alert_viewer -h
usage: fink_alert_viewer [-h] [-filename FILENAME]

Display cutouts and lightcurve from a ZTF alert

optional arguments:
  -h, --help          show this help message and exit
  -filename FILENAME  Path to an alert data file (avro format)
```

More information at [docs/livestream](https://fink-broker.readthedocs.io/en/latest/services/livestream).

## Data Transfer usage

If you requested data using the [Data Transfer service](https://fink-portal.org/download), you can easily poll your stream using:

```bash
usage: fink_datatransfer [-h] [-topic TOPIC] [-limit LIMIT] [-outdir OUTDIR] [-partitionby PARTITIONBY] [-batchsize BATCHSIZE] [-nconsumers NCONSUMERS] [-maxtimeout MAXTIMEOUT] [--restart_from_beginning] [--verbose]

Kafka consumer to listen and archive Fink streams from the data transfer service

optional arguments:
  -h, --help            show this help message and exit
  -topic TOPIC          Topic name for the stream that contains the data.
  -limit LIMIT          If specified, download only `limit` alerts from the stream. Default is None, that is download all alerts.
  -outdir OUTDIR        Folder to store incoming alerts. It will be created if it does not exist.
  -partitionby PARTITIONBY
                        Partition data by `time` (year=YYYY/month=MM/day=DD), or `finkclass` (finkclass=CLASS), or `tnsclass` (tnsclass=CLASS). `classId` is also available for ELASTiCC data. Default is time.
  -batchsize BATCHSIZE  Maximum number of alert within the `maxtimeout` (see conf). Default is 1000 alerts.
  -nconsumers NCONSUMERS
                        Number of parallel consumer to use. Default is 1.
  -maxtimeout MAXTIMEOUT
                        Overwrite the default timeout (in seconds) from user configuration. Default is None.
  --restart_from_beginning
                        If specified, restart downloading from the 1st alert in the stream. Default is False.
  --verbose             If specified, print on screen information about the consuming.

```

More information at [docs/datatransfer](https://fink-broker.readthedocs.io/en/latest/services/data_transfer/).