from pycoral.utils import edgetpu
from pycoral.utils import dataset
from pycoral.adapters import common
from pycoral.adapters import classify
from PIL import Image
from threading import Thread, Event
from queue import Queue, Empty
import numpy as np
from config import Classifiers
from json import dumps
from collections import deque

import logging

logger = logging.getLogger(__name__)

classifiers = Classifiers()


class Classify(object):
    """Classify images with TensorFlow and the Coral Edge TPU (threaded)"""

    def __init__(self):

        logger.info("Initialising classifier...")

        self.library = classifiers.get_classifiers()
        self.loaded = {}
        self.active = []

        self.quit_event = Event()
        self.file_queue = Queue()
        self.database = {}

    def _worker(self):

        logger.info("Initialising classification worker")

        while True:
            try:  # Timeout raises queue.Empty

                image = self.file_queue.get(block=True, timeout=0.1)

            except Empty:
                if self.quit_event.is_set():
                    logger.info("Quitting thread...")
                    break

            else:
                

                library = self.library
                active = self.active
                database = self.database

                # Iterate over all classifiers
                for name in library:

                    # Only classify active classifiers
                    if name in active:

                        # Ensure classifer is in database
                        try:
                            storage = database[name]
                            logger.info(' xxx %s is inside storage', storage)
                        except KeyError:
                            storage = {}

                        # Load classifier information
                        interpreter = self.loaded[name]["model"]
                        labels = self.loaded[name]["labels"]
                        thresholds = self.loaded[name]["thresholds"]
                        logger.info(' xxx %s is inside ["model"]', self.loaded[name]["model"])   
                                            
                        interpreter.allocate_tensors()
                        
                        size = common.input_size(interpreter)
                        image = Image.open(image).convert('RGB').resize(size, Image.ANTIALIAS)
                        
                        params = common.input_details(interpreter, 'quantization_parameters')
                        scale = params['scales']
                        zero_point = params['zero_points']
                        mean = 128 
                        std = 128  
                        
                        normalized_input = (np.asarray(image) - mean) / (std * scale) + zero_point
                        np.clip(normalized_input, 0, 255, out=normalized_input)
                        common.set_input(interpreter, normalized_input.astype(np.uint8))
                        
                        #common.set_input(engine, image)
                        interpreter.invoke()
                        # Run inference
                        logger.info("Starting classifier %s " % (name))
                        try:
                            results = classify.get_classes(
                                interpreter, top_k=3, score_threshold=0
                            )  # Return top 3 probability items
                            logger.info("%s results: " % (results))
                        except OSError:
                            logger.info("OSError detected, retrying")
                            break

                        # Create dictionary including those not in top_k
                        big_dict = {}
                        for result in results:
                            label = labels[result[0]]
                            confidence = round(result[1].item(), 2)
                            big_dict[label] = confidence
                        logger.info("%s: %.5f " % (labels.get(result.id,result.id), result.score))
                        not_in_top_k = big_dict.keys() ^ labels.values()
                        for label in not_in_top_k:
                            # Zero confidence ensures moving average keeps moving
                            big_dict[label] = 0

                        # Iterate over the dictionary
                        for label, confidence in big_dict.items():

                            # Ensure label is in classifier storage entry
                            if label not in storage:
                                storage[label] = {}
                                storage[label]["queue"] = [0] * 5

                            # Update nested storage dictionary
                            this_label = storage[label]
                            this_label["confidence"] = confidence

                            # Use deque to update moving average
                            queue = deque(this_label["queue"])
                            queue.append(confidence)
                            queue.popleft()
                            this_label["queue"] = list(queue)
                            average = round(sum(queue) / 5, 2)
                            this_label["average"] = average

                            # Use threshold storage to check whether it exceeds
                            this_label["threshold"] = thresholds[label]
                            this_label["boolean"] = average >= thresholds[label]

                        # Update database with all information from this classifier
                        database[name] = storage

                    # Remove classifiers in database that are not active
                    elif name in database:
                        del database[name]

                self.database = database

                self.file_queue.task_done()

    def load_classifiers(self, input_string):
        for name in input_string.split(","):

            # Check if classifier has already been loaded
            if name not in self.loaded:
                logger.info("Loading classifier %s " % (name))

                # Read attributes from library and initialise
                try:
                    attr = self.library[name]
                    output = {}
                    output["labels"] = dataset.read_label_file(attr["labels"])
                    logger.info("load_classifiers:%s", attr["labels"])
                    output["model"] = edgetpu.make_interpreter(attr["model"], device='usb:0')
                    logger.info("load_classifiers: %s", attr["model"])
                    output["thresholds"] = attr["thresholds"]
                    logger.info("load_classifiers:%s",attr["thresholds"])
                    self.loaded[name] = output
                except KeyError:
                    raise KeyError("Classifier name not found in database")
                except FileNotFoundError:
                    raise FileNotFoundError(
                        "Model or labels not found in models folder"
                    )

            else:
                logger.debug("Classifier already loaded %s " % (name))

    def set_classifiers(self, input_string):
        for name in input_string.split(","):

            # Check if classifier has already been loaded
            if name not in self.loaded:
                logger.debug("Classifier not loaded %s: loading " % (name))
                self.load_classifiers(name)
        self.active = input_string.split(",")

    def get_classifiers(self):
        return dumps(self.library)

    def start(self, file_path):
        logger.debug("Calling start")
        self.file_queue.put(file_path)

    def join(self):
        logger.debug("Calling join")
        self.file_queue.join()

    def launch(self):
        logger.debug("Initialising classification worker")
        self.thread = Thread(target=self._worker, daemon=True)
        self.thread.start()

    def quit(self):
        self.quit_event.set()
        logger.debug("Waiting for classification thread to finish")
        self.thread.join()
