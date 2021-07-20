import json
import os
import asyncio
import hafifa.utils.frame_utils as frame_utils
import hafifa.data_base.DataModelTransactions as DataModelTransactions
from flask import Flask, request
from hafifa.singleton import Singleton
from hafifa.logger.logger import Logger
from hafifa.data_base import data_models
from concurrent.futures import ThreadPoolExecutor
from hafifa.flask_app.FlaskConfig import FlaskConfig
from hafifa.data_base.SQLAlchemy import SQLAlchemyHandler
from hafifa.object_storage.azure_container_handler import AzureBlobContainerHandler


class FlaskAppHandler(metaclass=Singleton):
    def __init__(self):
        self.app = Flask(__name__, instance_relative_config=False)
        self.app.config.from_object(FlaskConfig)
        self.db = SQLAlchemyHandler(self.app)
        self.azure_container_handler = AzureBlobContainerHandler()

    def init_database(self):
        """
        Initiate database clear data models and create them
        """
        with self.app.app_context():
            self.db.clear_data_models()
            self.db.create_data_models()

    def run(self):
        self.app.add_url_rule('/video_path_by_id', view_func=self.get_video_path_by_id, methods=['POST'])
        self.app.add_url_rule('/get_videos_path', view_func=self.get_videos_path, methods=['GET'])
        self.app.add_url_rule('/upload_video', view_func=self.upload_video, methods=['POST'])
        self.app.run()

    def get_video_path_by_id(self):
        video_id = request.json['video_id']
        videos_dict = dict(self.db.get_table_columns(data_models.Video, ['id', 'os_path']))
        return json.dumps({'path': videos_dict[video_id]}), 200, {'ContentType': 'application/json'}

    def get_videos_path(self):
        return dict(self.db.get_table_columns(data_models.Video, ['id', 'os_path']))

    async def upload_video(self):
        """
        Get local video path upload to azure extract it to frames and metadata, create models and upload it to database.
        :return: server code.
        """
        local_video_path = request.json['video_path']
        Logger.logger.info(f'Start to handle path: {local_video_path}')

        video_file_name = os.path.basename(local_video_path)
        image_list = frame_utils.extract_video_to_frames(local_video_path)
        thread_pool = ThreadPoolExecutor(max_workers=3)

        upload_video_task = asyncio.create_task(
            self.azure_container_handler.upload_binary_file(local_video_path,
                                                            os.path.join('videos', video_file_name)))

        self.azure_container_handler.upload_images(image_list,
                                                   os.path.join('frames', video_file_name),
                                                   thread_pool,
                                                   local_video_path)

        DataModelTransactions.create_and_insert_to_database_video_metadata_frame_models(local_video_path,
                                                                                        image_list,
                                                                                        video_file_name)

        await upload_video_task
        thread_pool.shutdown(wait=True)

        Logger.logger.info(f'Finish to handle path: {local_video_path}')

        return json.dumps({'success': True}), 200, {'ContentType': 'application/json'}
