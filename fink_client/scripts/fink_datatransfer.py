""" Kafka consumer to listen and archive Fink streams
    from the data transfer service
"""
import sys
import os
import io
import json
import argparse
import logging

from tqdm import trange

import pyarrow as pa
import pyarrow.parquet as pq
import fastavro
import confluent_kafka

import pandas as pd

from multiprocessing import Process, Queue

from fink_client.configuration import load_credentials

from fink_client.consumer import return_offsets


def print_offsets(kafka_config, topic, maxtimeout=10, verbose=True):
    """ Wrapper around `consumer.return_offsets`

    If the server is rebalancing the offsets, it will exit the program.

    Parameters
    ----------
    kafka_config: dic
        Dictionary with consumer parameters
    topic: str
        Topic name
    maxtimeout: int, optional
        Timeout in second, when polling the servers

    Returns
    ----------
    total_offsets: int
        Total number of messages committed across all partitions
    total_lag: int
        Remaining messages in the topic across all partitions.
    """
    consumer = confluent_kafka.Consumer(kafka_config)

    topics = ['{}'.format(topic)]
    consumer.subscribe(topics)
    total_offset, total_lag = return_offsets(consumer, topic, timeout=maxtimeout, waitfor=0, verbose=verbose)
    if (total_offset, total_lag) == (-1, -1):
        print("Warning: Consumer group '{}' is rebalancing. Please wait.".format(kafka_config['group.id']))
        sys.exit()
    consumer.close()

    return total_lag, total_offset


def get_schema(kafka_config, topic, maxtimeout):
    """ Poll the schema data from the schema topic

    Parameters
    ----------
    kafka_config: dic
        Dictionary with consumer parameters
    topic: str
        Topic name
    timeout: int, optional
        Timeout in second, when polling the servers

    Returns
    ----------
    schema: None or dic
        Schema data. None if the poll was not successful.
        Reasons to get None:
            1. timeout has been reached (increase timeout)
            2. topic is empty (produce new data)
            3. topic does not exist (create the topic)
    """
    # Instantiate a consumer
    consumer_schema = confluent_kafka.Consumer(kafka_config)

    # Subscribe to schema topic
    topics = ['{}_schema'.format(topic)]
    consumer_schema.subscribe(topics)

    # Poll
    msg = consumer_schema.poll(maxtimeout)
    if msg is not None:
        schema = fastavro.schema.parse_schema(json.loads(msg.key()))
    else:
        schema = None

    consumer_schema.close()

    return schema


def my_assign(consumer, partitions):
    """ Function to reset offsets when (re)polling

    It must be passed when subscribing to a topic:
        `consumer.subscribe(topics, on_assign=my_assign)`

    Parameters
    ----------
    consumer: confluent_kafka.Consumer
        Kafka consumer
    partitions: Kafka partitions
        Internal object to deal with partitions
    """
    for p in partitions:
        p.offset = 0
    consumer.assign(partitions)


def reset_offset(kafka_config, topic):
    """
    """
    consumer = confluent_kafka.Consumer(kafka_config)
    topics = ['{}'.format(topic)]
    consumer.subscribe(topics, on_assign=my_assign)
    consumer.close()


def return_partition_offset(consumer, topic, partition):
    """ Return the offset and the remaining lag of a partition

    consumer: confluent_kafka.Consumer
        Kafka consumer
    topic: str
        Topic name
    partition: int
        The partition

    Returns
    ----------
    offset : int
        Total number of offsets in the topic
    """

    topicPartition = confluent_kafka.TopicPartition(topic, partition)
    low_offset, high_offset = consumer.get_watermark_offsets(topicPartition)
    partition_size = high_offset - low_offset

    return partition_size


def return_npartitions(topic, kafka_config):
    """ Function to get the number partition

        Parameters
        ----------
        kafka_config: dic
            Dictionary with consumer parameters
        topic: str
            Topic name

        Returns
        ----------
        nbpartitions: int
            Number of partitions in the topic

    """
    consumer = confluent_kafka.Consumer(kafka_config)

    # Details to get
    nbpartitions = 0
    try:
        # Obtenez les métadonnées du topic
        metadata = consumer.list_topics(topic=topic)

        if metadata.topics and topic in metadata.topics:
            partitions = metadata.topics[topic].partitions
            nbpartitions = len(partitions)
        else:
            print("Le topic", topic, "n'existe pas.")

    except confluent_kafka.KafkaException as e:
        print(f"Erreur lors de la récupération du nombre de partitions du topic: {e}")

    consumer.close()

    return nbpartitions


def return_last_offsets(kafka_config, topic):
    """

    Parameters
    ----------
    kafka_config: dict
        Kafka consumer config
    topic: str
        Topic name

    Returns
    ----------
    offsets: list
        Last offsets of each partition
    """
    consumer = confluent_kafka.Consumer(kafka_config)
    topics = ['{}'.format(topic)]
    consumer.subscribe(topics)

    metadata = consumer.list_topics(topic)
    if metadata.topics[topic].error is not None:
        raise confluent_kafka.KafkaException(metadata.topics[topic].error)
    # List of partition
    partitions = [confluent_kafka.TopicPartition(topic, p) for p in metadata.topics[topic].partitions]
    committed = consumer.committed(partitions)
    offsets = []
    for partition in committed:
        if partition.offset != confluent_kafka.OFFSET_INVALID:
            offsets.append(partition.offset)
        else:
            offsets.append(0)

    consumer.close()
    return offsets


def poll(processId, queue, schema, kafka_config, args):
    """ Poll data from Kafka servers

    Parameters
    ----------
    processId: int
        ID of the process used for multiprocessing
    queue: Multiprocessing.Queue
        Shared queue between processes where are stocked partitions and the last offset of the partition
    schema: dict
        Alert schema
    kafka_config: dict
        Configuration to instantiate a consumer
    args: dict
        Other arguments (topic, maxtimeout, total_offset, total_lag)
        required for the processing
    """
    # Instantiate a consumer
    consumer = confluent_kafka.Consumer(kafka_config)
    # Subscribe to schema topic
    # topics = ['{}'.format(args.topic)]

    # infinite loop
    maxpoll = int(args.limit / args.nconsumers) if args.limit is not None else 1e10
    disable = not args.verbose

    poll_number = 0
    while not queue.empty() and poll_number < maxpoll:
        # Getting a partition from the queue
        partition = queue.get()
        tp = confluent_kafka.TopicPartition(
            args.topic,
            partition["partition"],
            offset=partition["offset"]
        )
        consumer.assign([tp])
        # Getting the total number of alert in the partition
        offset = return_partition_offset(
            consumer,
            args.topic,
            partition["partition"]
        )
        # Resuming from the last consumed alert
        initial = partition["offset"]

        max_end_check = 4

        if offset == initial:
            if partition["status"] < max_end_check:
                # After max_end_check time if no alerts added,
                # it is supposed finished
                queue.put({
                    "partition": partition["partition"],
                    "offset": partition["offset"],
                    "status": partition["status"] + 1
                })
        else:
            poll_number = initial
            total = offset
            with trange(total, position=partition["partition"], initial=initial, colour='#F5622E', unit='alerts', disable=disable) as pbar:
                try:
                    while poll_number < maxpoll:
                        msgs = consumer.consume(
                            args.batchsize,
                            args.maxtimeout
                        )
                        # Decode the message
                        if msgs is not None:
                            if len(msgs) == 0:
                                print('[{}] No alerts the last {} seconds ({} polled)... Have to exit(1)\n'.format(processId, args.maxtimeout, poll_number))
                                # Alerts can be added in the partition later
                                # putting it again in the queue
                                # changing the offset to continue where we stopped
                                queue.put({
                                    "partition": partition["partition"],
                                    "offset": poll_number,
                                    "status": 0
                                })
                                break

                            pdf = pd.DataFrame.from_records(
                                [fastavro.schemaless_reader(io.BytesIO(msg.value()), schema) for msg in msgs],
                            )
                            if pdf.empty:
                                # print('[{}] No alerts the last {} seconds ({} polled)... Exiting\n'.format(processId, args.maxtimeout, poll_number))
                                break

                            # known mismatches between partitions
                            # see https://github.com/astrolabsoftware/fink-client/issues/165
                            if 'cats_broad_max_prob' in pdf.columns:
                                pdf['cats_broad_max_prob'] = pdf['cats_broad_max_prob'].astype('float')

                            if 'cats_broad_class' in pdf.columns:
                                pdf['cats_broad_class'] = pdf['cats_broad_class'].astype('float')

                            if 'tracklet' in pdf.columns:
                                pdf['tracklet'] = pdf['tracklet'].astype('str')

                            # if 'jd' in pdf.columns:
                            #     # create columns year, month, day

                            table = pa.Table.from_pandas(pdf)

                            if poll_number == initial:
                                table_schema = table.schema

                            if args.partitionby == 'time':
                                partitioning = ['year', 'month', 'day']
                            elif args.partitionby == 'finkclass':
                                partitioning = ['finkclass']
                            elif args.partitionby == 'tnsclass':
                                partitioning = ['tnsclass']
                            elif args.partitionby == 'classId':
                                partitioning = ['classId']

                            try:
                                pq.write_to_dataset(
                                    table,
                                    args.outdir,
                                    schema=table_schema,
                                    basename_template='part-{}-{{i}}-{}.parquet'.format(processId, poll_number),
                                    partition_cols=partitioning,
                                    existing_data_behavior='overwrite_or_ignore'
                                )
                            except pa.lib.ArrowTypeError:
                                print('Schema mismatch detected')
                                table_schema_ = table.schema
                                pq.write_to_dataset(
                                    table,
                                    args.outdir,
                                    schema=table_schema_,
                                    basename_template='part-{}-{{i}}-{}.parquet'.format(processId, poll_number),
                                    partition_cols=partitioning,
                                    existing_data_behavior='overwrite_or_ignore'
                                )

                            poll_number += len(msgs)
                            pbar.update(len(msgs))

                            if len(msgs) < args.batchsize:
                                queue.put({
                                    "partition": partition["partition"],
                                    "offset": poll_number,
                                    "status": 0
                                })
                                break
                        else:
                            logging.info('[{}] No alerts the last {} seconds ({} polled)\n'.format(processId, args.maxtimeout, poll_number))
                except KeyboardInterrupt:
                    sys.stderr.write('%% Aborted by user\n')
                    consumer.close()
    consumer.close()


def main():
    """ """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '-topic', type=str, default='.',
        help="Topic name for the stream that contains the data.")
    parser.add_argument(
        '-limit', type=int, default=None,
        help="If specified, download only `limit` alerts from the stream. Default is None, that is download all alerts.")
    parser.add_argument(
        '-outdir', type=str, default='.',
        help="Folder to store incoming alerts. It will be created if it does not exist.")
    parser.add_argument(
        '-partitionby', type=str, default='time',
        help="Partition data by `time` (year=YYYY/month=MM/day=DD), or `finkclass` (finkclass=CLASS), or `tnsclass` (tnsclass=CLASS). `classId` is also available for ELASTiCC data. Default is time.")
    parser.add_argument(
        '-batchsize', type=int, default=1000,
        help="Maximum number of alert within the `maxtimeout` (see conf). Default is 1000 alerts.")
    parser.add_argument(
        '-nconsumers', type=int, default=1,
        help="Number of parallel consumer to use. Default is 1.")
    parser.add_argument(
        '-maxtimeout', type=float, default=None,
        help="Overwrite the default timeout (in seconds) from user configuration. Default is None.")
    parser.add_argument(
        '--restart_from_beginning', action='store_true',
        help="If specified, restart downloading from the 1st alert in the stream. Default is False.")
    parser.add_argument(
        '--verbose', action='store_true',
        help="If specified, print on screen information about the consuming.")
    args = parser.parse_args(None)

    if args.partitionby not in ['time', 'finkclass', 'tnsclass', 'classId']:
        print("{} is an unknown partitioning. `-partitionby` should be in ['time', 'finkclass', 'tnsclass', 'classId']".format(args.partitionby))
        sys.exit()

    # load user configuration
    conf = load_credentials()

    # Time to wait before polling again if no alerts
    if args.maxtimeout is None:
        args.maxtimeout = conf['maxtimeout']

    kafka_config = {
        'bootstrap.servers': conf['servers'],
        'group.id': conf['group_id'],
        "auto.offset.reset": "earliest"
    }

    if args.restart_from_beginning:
        total_lag, total_offset = print_offsets(kafka_config, args.topic, args.maxtimeout, verbose=False)
        args.total_lag = total_offset
        args.total_offset = 0
        offsets = [0 for _ in range(10)]
    else:
        total_lag, total_offset = print_offsets(kafka_config, args.topic, args.maxtimeout)
        args.total_lag = total_lag
        args.total_offset = total_offset
        offsets = return_last_offsets(kafka_config, args.topic)
        if total_lag == 0:
            print("All alerts have been polled. Exiting.")
            sys.exit()

    if not os.path.isdir(args.outdir):
        os.makedirs(args.outdir, exist_ok=True)

    if (args.limit is not None) and (args.limit < args.batchsize):
        args.batchsize = args.limit

    schema = get_schema(kafka_config, args.topic, args.maxtimeout)
    if schema is None:
        # TBD: raise error
        print('No schema found -- wait a few seconds and relaunch. If the error persists, maybe the queue is empty.')
    else:
        # processIds = [i for i in range(args.nconsumers)]
        # schemas = np.tile(schema, args.nconsumers)
        # kafka_configs = np.tile(kafka_config, args.nconsumers)
        # args_list = np.tile(args, args.nconsumers)
        nbpart = return_npartitions(args.topic, kafka_config)
        print("Le nombre de partitions du topic", args.topic, "est", nbpart)
        available = Queue()
        # Queue loading
        for key in range(nbpart):
            available.put({
                "partition": key,
                "offset": offsets[key],
                "status": 0
            })

        # Processes Creation
        procs = []
        for i in range(args.nconsumers):
            proc = Process(target=poll, args=(i, available, schema, kafka_config, args))
            procs.append(proc)
            proc.start()

        for proc in procs:
            proc.join()

        print_offsets(kafka_config, args.topic, args.maxtimeout)


if __name__ == "__main__":
    main()
