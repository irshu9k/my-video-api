# app.py
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/")
def index():
    return jsonify({"message": "API Ready!"})

# Your full /generate-video route and logic goes here
