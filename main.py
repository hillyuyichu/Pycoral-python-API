from threading import Thread, Event
from time import sleep

from thermal_camera import ThermalCamera
from camera import Camera
from cloud import Cloud
from classification import Classify
from control import Control
from data import Data
from config import Settings, Labels

from datetime import datetime
from json import dumps
import logging

# Fix logging faliure issue
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

# Initialise custom logging format
FORMAT = "%(relativeCreated)6d %(levelname)-8s %(name)s %(process)d %(message)s"
logging.basicConfig(format=FORMAT, level=logging.INFO)
logger = logging.getLogger(__name__)

settings = Settings()
labels = Labels()
camera = Camera()
thermal = ThermalCamera()
cloud = Cloud()
classify = Classify()
data = Data()
control = Control()


class OnionBot(object):
    """Main OnionBot script"""

    def __init__(self):

        self.quit_event = Event()

        # Launch multiprocessing threads
        logger.info("Launching worker threads...")
        thermal.launch()
        cloud.launch_camera()
        cloud.launch_thermal()
        classify.launch()
        control.launch()

        self.latest_meta = " "
        self.session_ID = None
        self.label = None

        logger.info("OnionBot is ready")

    def run(self):
        """Start logging"""

        def _worker():

            measurement_ID = 0
            file_data = None
            meta = None

            while True:

                # Get time stamp
                timer = datetime.now()

                # Get update on key information
                measurement_ID += 1
                label = self.label
                session_ID = self.session_ID

                # Generate file_data for logs
                queued_file_data = data.generate_file_data(
                    session_ID, timer, measurement_ID, label
                )

                # Generate metadata for frontend
                queued_meta = data.generate_meta(
                    session_ID=session_ID,
                    timer=timer,
                    measurement_ID=measurement_ID,
                    label=label,
                    file_data=queued_file_data,
                    thermal_data=thermal.data,
                    control_data=control.data,
                    classification_data=classify.database,
                )

                # Start sensor capture
                logger.info("just before cam_file")
                cam_file = camera.capture(queued_file_data["camera_file"])
                logger.info("passed cam_file")
                thermal.start(queued_file_data["thermal_file"])
                logger.info("passed thermal.start")

                # While taking a picture, process previous data in meantime
                if file_data:
                    logger.info("in file_data")
                    cloud.start_camera(cam_file)
                    logger.info("passed cloud.start_cam")
                    cloud.start_thermal(file_data["thermal_file"])
                    logger.info("passed cloud.start_thermy_cam")
                    classify.start(file_data["camera_file"])
                    logger.info("passed classify.start")

                    # Wait for all meantime processes to finish
                    classify.join()
                    cloud.join_camera()
                    cloud.join_thermal()
                    

                    # Push meta information to file level for API access
                    self.labels_csv_filepath = file_data["label_file"]
                    self.latest_meta = dumps(meta)

                # Wait for queued image captures to finish, refresh control data
                thermal.join()
                control.refresh(thermal.data["temperature"])

                # Log to console
                if meta is not None:
                    attributes = meta["attributes"]
                

                # Move queue forward one place
                file_data = queued_file_data
                meta = queued_meta

                # Add delay until ready for next loop
                frame_interval = float(settings.get_setting("frame_interval"))
                while True:
                    if (datetime.now() - timer).total_seconds() > frame_interval:
                        break
                    elif self.quit_event.is_set():
                        break
                    sleep(0.01)

                # Check quit flag
                if self.quit_event.is_set():
                    logger.debug("Quitting main thread...")
                    break

        # Start thread
        logger.info("Starting main script")
        self.thread = Thread(target=_worker, daemon=True)
        self.thread.start()

    def start(self, session_ID):
        data.start_session(session_ID)
        self.session_ID = session_ID

    def stop(self):
        """Stop logging"""
        self.session_ID = None
        labels = self.labels_csv_filepath
        cloud.start_camera(
            labels
        )  # Use cloud uploader camera thread to upload label file
        cloud.join_camera()
        return cloud.get_public_path(labels)

    def get_latest_meta(self):
        """Returns cloud filepath of latest meta.json - includes path location of images"""
        return self.latest_meta

    def get_thermal_history(self):
        """Returns last 300 temperature readings"""
        return self.thermal_history

    def set_label(self, string):
        """Command to change current label -  for building training datasets"""
        self.label = string

    def set_no_label(self):
        """Command to set label to None type"""
        self.label = None

    def set_classifiers(self, string):
        """Command to change current classifier for predictions"""
        classify.set_classifiers(string)

    def set_fixed_setpoint(self, value):
        """Command to change fixed setpoint"""
        control.update_fixed_setpoint(value)

    def set_temperature_target(self, value):
        """Command to change temperature target"""
        control.update_temperature_target(value)

    def set_temperature_hold(self):
        """Command to hold current temperature"""
        control.hold_temperature()

    def set_hob_off(self):
        """Command to turn hob off"""
        control.hob_off()

    def set_frame_interval(self, value):
        """Command to change camera target refresh rate"""
        settings.set_setting("frame_interval", value)

    def get_all_labels(self):
        """Returns available image labels for training"""
        return labels.get_labels()

    def get_all_classifiers(self):
        """Returns available models for prediction"""
        return classify.get_classifiers()
    '''
    def set_pid_enabled(self, enabled):
        """Command to start PID controller"""
        control.set_pid_enabled(enabled)

    def set_p_coefficient(self, coefficient):
        """Command to set PID P coeffient"""
        control.set_p_coefficient(coefficient)

    def set_i_coefficient(self, coefficient):
        """Command to set PID I coeffient"""
        control.set_i_coefficient(coefficient)

    def set_d_coefficient(self, coefficient):
        """Command to set PID D coeffient"""
        control.set_d_coefficient(coefficient)

    def set_pid_reset(self):
        """Command to reset PID components to 0 (not to be confused with coefficients)"""
        control.set_pid_reset()
    '''
    def quit(self):
        logger.info("Raising exit flag")
        self.quit_event.set()
        self.thread.join()
        logger.info("Main module quit")
        control.quit()
        logger.info("Control module quit")
        thermal.quit()
        logger.info("Thermal module quit")
        cloud.quit()
        logger.info("Cloud module quit")
        classify.quit()
        logger.info("Classifier module quit")
        logger.info("Quit process complete")
        #camera.mp_quit()
        #logger.info("Camera module quit")

