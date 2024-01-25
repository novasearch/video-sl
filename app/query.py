import datetime
import json
import os
import re

from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for
)

FRAMES_PATH = "app/static/videofiles/frames"
ANNOTATIONS_PATH = "app/static/videofiles/annotations"

PHRASES_ID = "LP_P1 transcrição livre"
FACIAL_EXPRESSIONS_ID = "GLOSA_P1_EXPRESSAO"

bp = Blueprint('query', __name__)


@bp.route("/", methods=("GET", "POST"))
def query():
    """Query for a video."""
    if request.method == "POST":
        query_input = request.form["query"]
        selected_field = int(request.form.get('field'))
        session['search_mode'] = request.form.get('mode')
        error = None

        if not query_input:
            error = "Query is required."

        if error is not None:
            flash(error)
        else:

            # TODO: Query opensearch for videos matching query
            if selected_field == 1:  # Frames Embeddings
                flash("Not Implemented")
            elif selected_field == 2:  # Average Frames Embeddings
                flash("Not Implemented")
            elif selected_field == 3:  # Best Frame Embedding
                flash("Not Implemented")
            elif selected_field == 4:  # True Expression
                session['query_results'] = query_true_expression(query_input)

            return redirect(url_for("query.results"))

    return render_template("query/query.html")


@bp.route("/results", methods=("GET", "POST"))
def results():
    """Display results of query."""
    query_results = session.get('query_results', [])
    search_mode = session.get('search_mode', 1)

    frames = {}
    frames_info = {}

    # Get the searched frames
    for retrieved_annotation in query_results:
        video, annotation_id = retrieved_annotation.split('_')

        annotation_path = os.path.join(ANNOTATIONS_PATH, f"{video}.json")
        with open(annotation_path, "r") as f:
            annotations = json.load(f)
            for annotation in annotations[search_mode]["annotations"]:
                if annotation["annotation_id"] == annotation_id:
                    frames_path = os.path.join(FRAMES_PATH, search_mode, video, annotation_id)
                    frames[retrieved_annotation] = os.listdir(frames_path)
                    frames_info[retrieved_annotation] = annotation
                    converted_start_time = str(datetime.timedelta(seconds=int(annotation["start_time"]) // 1000))
                    frames_info[retrieved_annotation]["converted_start_time"] = converted_start_time
                    break

    if search_mode == FACIAL_EXPRESSIONS_ID:
        # Not all frames of each expression are going to be displayed
        frames_to_display = {}
        num_frames_to_display = 8

        # Display only #num_frames_to_display frames of each expression
        for expression, all_frames in frames.items():

            # Calculate the step size
            if len(all_frames) <= num_frames_to_display:
                step_size = 1
            else:
                # Calculate the step size
                step_size = (len(all_frames) - 1) // num_frames_to_display + 1

            # Select frames to display
            frames_to_display[expression] = all_frames[::step_size]

            # Ensure that only num_frames_to_display frames are selected
            frames_to_display[expression] = frames_to_display[expression][:num_frames_to_display]
    else:
        # If the frames are not the facial expression's ones then it just has one frame per result
        frames_to_display = frames

    if request.method == "POST":
        selected_result = request.form.get("selected_result")
        video, annotation_id = selected_result.split('_')
        annotation = frames_info[selected_result]

        error = None

        if not selected_result:
            error = "Expression is required."

        if error is not None:
            flash(error)
        else:

            session['annotation'] = annotation
            return redirect(url_for("query.play_selected_result", video=video, annotation_id=annotation_id))

    return render_template("query/results.html", frames=frames_to_display, frames_info=frames_info,
                           search_mode=search_mode)


@bp.route("/results/<video>/<annotation_id>", methods=("GET", "POST"))
def play_selected_result(video, annotation_id):
    """ Display the video clip of the selected expression. """

    annotation = session.get('annotation')

    # Convert the timestamp to seconds
    timestamp_seconds = int(annotation["start_time"]) // 1000

    return render_template("query/play_expression.html", value=annotation["value"], video=video,
                           timestamp=timestamp_seconds)


def query_true_expression(query_input):
    """ Get the results of the query using the ground truth """
    query_results = []
    search_mode = session.get('search_mode', 1)

    for video in os.listdir(os.path.join(FRAMES_PATH, search_mode)):
        with open(os.path.join(ANNOTATIONS_PATH, f"{video}.json"), "r") as f:
            video_annotations = json.load(f)
            if search_mode in video_annotations:
                for annotation in video_annotations[search_mode]["annotations"]:
                    if annotation["value"] is not None and query_input.lower() in annotation["value"].lower():
                        query_results.append(video + "_" + annotation["annotation_id"])

    return query_results
