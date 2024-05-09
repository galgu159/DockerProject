import json
import time
from pathlib import Path
import boto3
import pymongo
from flask import Flask, request
from detect import run
import uuid
import yaml
from loguru import logger
import os
import logging
from pymongo import MongoClient
from bson import json_util

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get the bucket name from the environment variable
images_bucket = os.environ['BUCKET_NAME']

# Open the YAML file in read mode
with open("data/coco128.yaml", "r") as stream:
    # Load the YAML content safely, Extract the value associated with the key 'names'
    names = yaml.safe_load(stream)['names']

app = Flask(__name__)

@app.route('/predict', methods=['POST'])
def predict():
    # Generates a UUID for this current prediction HTTP request. This id can be used as a reference in logs to identify and track individual prediction requests.
    prediction_id = str(uuid.uuid4())

    logger.info(f'prediction: {prediction_id}. start processing')

    # Receives a URL parameter representing the image to download from S3
    img_name = request.json.get('imgName')
    logger.info(f'img_name is received is {img_name}')
    photo_s3_name = img_name.split("/")
    file_path_pic_download = os.getcwd() + "/" + str(photo_s3_name[1])
    logger.info(file_path_pic_download)
    client = boto3.client('s3')
    client.download_file(images_bucket, str(photo_s3_name[1]), file_path_pic_download)

    # TODO download img_name from S3, store the local image path in the original_img_path variable.
    #  The bucket name is provided as an env var BUCKET_NAME.
    original_img_path = file_path_pic_download
    logger.info(f'prediction: {prediction_id}/{original_img_path}. Download img completed')

    # Predicts the objects in the image
    run(
        weights='yolov5s.pt',
        data='data/coco128.yaml',
        source=original_img_path,
        project='static/data',
        name=prediction_id,
        save_txt=True
    )

    # This is the path for the predicted image with labels
    # The predicted image typically includes bounding boxes drawn around the detected objects, along with class labels and possibly confidence scores.
    path = Path(f'static/data/{prediction_id}/{str(photo_s3_name[1])}')
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        pass

    predicted_img_path = Path(f'static/data/{prediction_id}/{str(photo_s3_name[1])}')
    path_str = str(predicted_img_path)
    json_str = json.dumps({"path": path_str})
    json_data = json.loads(json_str)
    unique_filename = str(uuid.uuid4()) + '.jpeg'
    client.upload_file(json_data["path"], images_bucket, unique_filename)

    # Parse prediction labels and create a summary
    path = Path(f'static/data/{prediction_id}/labels/{photo_s3_name[1].split(".")[0]}.txt')
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        pass

    pred_summary_path = Path(f'static/data/{prediction_id}/labels/{photo_s3_name[1].split(".")[0]}.txt')
    if pred_summary_path.exists():
        with open(pred_summary_path) as f:
            labels = f.read().splitlines()
            labels = [line.split(' ') for line in labels]
            labels = [{
                'class': names[int(l[0])],
                'cx': float(l[1]),
                'cy': float(l[2]),
                'width': float(l[3]),
                'height': float(l[4]),
            } for l in labels]
            logger.info(f'prediction: {prediction_id}/{photo_s3_name[1]}. prediction summary:\n\n{labels}')
            prediction_summary = {
                'prediction_id': prediction_id,
                'original_img_path': photo_s3_name[1],
                'predicted_img_path': json_data["path"],
                'labels': labels,
                'time': time.time()
            }

            try:
                logger.info("Connecting to MongoDB...")
                connection_string = f"mongodb://mongo_1:27017/"
                logger.info(f"Connection string: {connection_string}")
                client = MongoClient(connection_string)
                logger.info("MongoClient connected successfully.")
                db = client['mydatabase']
                collection_name = 'prediction'
                collection = db['prediction']
                logger.info("Inserting data...")
                collection.insert_one(prediction_summary)
                logger.info("Data inserted successfully.")
                doc = collection.find_one({})
                json_doc = json.dumps(doc, default=json_util.default)
                class_counts = {}
                for label in labels:
                    class_name = label['class']
                    if class_name in class_counts:
                        class_counts[class_name] += 1
                    else:
                        class_counts[class_name] = 1
                # Create a dictionary with class names and counts
                class_counts_json = {class_name: count for class_name, count in class_counts.items()}
                # Convert the dictionary to JSON
                class_counts_json_str = json.dumps(class_counts_json)
                # Return the JSON object
                return class_counts_json
                

            except Exception as e:
                logger.error(f"Error connecting to MongoDB or inserting data:\n {e}")

    else:
        return f'prediction: {prediction_id}/{original_img_path}. prediction result not found', 404

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8081 , debug=True)

