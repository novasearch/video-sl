import datetime
import json
import os
import pickle
import re
from collections import OrderedDict

from flask import (
    Blueprint, flash, redirect, render_template, request, session, url_for
)

from .embeddings import embeddings_processing
from .opensearch.opensearch import LGPOpenSearch
from .constants import EMBEDDINGS_PATH, FRAMES_PATH, FACIAL_EXPRESSIONS_ID, PHRASES_ID, ANNOTATIONS_PATH

N_RESULTS = 10
N_FRAMES_TO_DISPLAY = 6

bp = Blueprint('query', __name__)
opensearch = LGPOpenSearch()
embedder = embeddings_processing.Embedder(check_gpu=False)


@bp.route("/", methods=("GET", "POST"))
def query():
    """Query for a video"""
    if request.method == "POST":
        query_input = request.form["query"]
        session['query_input'] = query_input
        selected_field = int(request.form.get('field'))
        session['search_mode'] = request.form.get('mode')
        error = None

        if not query_input:
            error = "Query is required."

        if error is not None:
            flash(error)
        else:

            if selected_field == 1:  # Base Frames Embeddings
                session['query_results'] = query_frames_embeddings(query_input)
            elif selected_field == 2:  # Average Frames Embeddings
                session['query_results'] = query_average_frames_embeddings(query_input)
            elif selected_field == 3:  # Best Frame Embeddings
                session['query_results'] = query_best_frame_embedding(query_input)
            elif selected_field == 4:  # Annotations Embeddings
                session['query_results'] = query_annotations_embeddings(query_input)
            else:  # True Expression / Ground Truth
                session['query_results'] = query_true_expression(query_input)

            # If there are no results, display a message
            if query_input is not None and not session['query_results']:
                flash("No results found.")
                return render_template("query/query.html")

            return redirect(url_for("query.videos_results"))

    return render_template("query/query.html")


@bp.route("/videos_results", methods=("GET", "POST"))
def videos_results():
    """ Display the videos that contain the query results """
    query_results = session.get('query_results')
    search_mode = session.get('search_mode', 1)

    # Sort the query results by the number of annotations
    query_results = OrderedDict(sorted(query_results.items(), key=lambda x: len(x[1]), reverse=True))

    frames = {}
    videos_info = {}

    # Collect information about the retrieved videos
    for video_id in query_results:
        annotations = query_results[video_id]
        first_annotation = list(annotations.keys())[0]

        videos_info[video_id] = {}
        videos_info[video_id]['video_name'] = video_id
        videos_info[video_id]['n_annotations'] = len(annotations)
        videos_info[video_id]['first_annotation'] = first_annotation

        # Get the first frame of the first annotation to display in the results page
        frames_path = os.path.join(FRAMES_PATH, search_mode, video_id, first_annotation)
        frames[video_id] = os.listdir(frames_path)[0]

    if request.method == "POST":
        selected_video = request.form.get("selected_video")
        error = None

        if not selected_video:
            error = "Selecting a video is required."

        if error is not None:
            flash(error)
        else:
            return redirect(url_for("query.clips_results", video=selected_video))

    return render_template("query/videos_results.html", frames=frames, videos_info=videos_info,
                           search_mode=search_mode)


@bp.route("/clips_results/<video>", methods=("GET", "POST"))
def clips_results(video):
    """ Display the video segments of one video that contain the query results """
    query_results = session.get('query_results')[video]
    query_input = session.get('query_input')
    search_mode = session.get('search_mode', 1)

    # Sort the query results by similarity score
    query_results = OrderedDict(sorted(query_results.items(), key=lambda x: x[1]['similarity_score'], reverse=True))

    frames = {}
    # frames_info = {}

    # Collect information about the retrieved video segments
    for annotation_id in query_results:
        frames_path = os.path.join(FRAMES_PATH, search_mode, video, annotation_id)
        frames[annotation_id] = os.listdir(frames_path)

        converted_start_time = str(datetime.timedelta(seconds=int(query_results[annotation_id]["start_time"]) // 1000))
        converted_end_time = str(datetime.timedelta(seconds=int(query_results[annotation_id]["end_time"]) // 1000))

        query_results[annotation_id]["converted_start_time"] = converted_start_time
        query_results[annotation_id]["converted_end_time"] = converted_end_time

    if search_mode == FACIAL_EXPRESSIONS_ID:
        # Not all frames of each expression are going to be displayed
        frames_to_display = get_frames_to_display(frames)

        if request.method == "POST":
            button_clicked = request.form.get("button_clicked")
            selected_annotation = request.form.get("selected_annotation")

            if button_clicked == 'edit':
                return redirect(url_for("annotations.edit_annotation", video_id=video, annotation_id=selected_annotation))

            elif button_clicked == 'thesaurus':
                return redirect(url_for("query.thesaurus_results", video_id=video, annotation_id=selected_annotation))

        return render_template("query/clips_results/expressions_clips.html", frames=frames_to_display,
                               frames_info=query_results, query_input=query_input,
                               search_mode=search_mode, video=video)
    elif search_mode == PHRASES_ID:

        # Display all frames of each phrase
        frames_to_display = frames

        return render_template("query/clips_results/phrases_clips.html", frames=frames_to_display,
                               frames_info=query_results, query_input=query_input,
                               search_mode=search_mode, video=video)


@bp.route("/thesaurus/<video_id>/<annotation_id>", methods=("GET", "POST"))
def thesaurus_results(video_id, annotation_id):
    """ Display the thesaurus results for a similar sign """
    search_results = query_thesaurus(video_id, annotation_id)
    search_mode = session.get('search_mode', 1)

    frames = {}

    # Collect information about the retrieved video segments
    for video_id in search_results:
        for annotation_id in search_results[video_id]:
            frames_path = os.path.join(FRAMES_PATH, search_mode, video_id, annotation_id)

            frames[video_id + "_" + annotation_id] = os.listdir(frames_path)

            converted_start_time = str(
                datetime.timedelta(seconds=int(search_results[video_id][annotation_id]["start_time"]) // 1000))
            converted_end_time = str(
                datetime.timedelta(seconds=int(search_results[video_id][annotation_id]["end_time"]) // 1000))

            search_results[video_id][annotation_id]["converted_start_time"] = converted_start_time
            search_results[video_id][annotation_id]["converted_end_time"] = converted_end_time

    # Not all frames of each expression are going to be displayed
    frames_to_display = get_frames_to_display(frames)

    # Initialize a dictionary to store the frames information so that the keys
    # are a composition of the video_id and the annotation_id
    frames_info = {}
    for video_id in search_results:
        for annotation_id in search_results[video_id]:
            frames_info[video_id + "_" + annotation_id] = search_results[video_id][annotation_id]
            frames_info[video_id + "_" + annotation_id]["annotation_id"] = annotation_id

    return render_template("query/clips_results/thesaurus_clips.html", frames=frames_to_display,
                           frames_info=frames_info, search_mode=search_mode, video=video_id)


def query_frames_embeddings(query_input):
    """ Get the results of the query using the frames embeddings """
    query_embedding = embeddings_processing.generate_query_embeddings(query_input, embedder)
    search_results = opensearch.knn_query(query_embedding.tolist(), N_RESULTS)
    return set_query_results(search_results, query_input)


def query_average_frames_embeddings(query_input):
    """ Get the results of the query using the average of the frames embeddings """
    query_embedding = embeddings_processing.generate_query_embeddings(query_input, embedder)
    search_results = opensearch.knn_query_average(query_embedding.tolist(), N_RESULTS)
    return set_query_results(search_results, query_input)


def query_best_frame_embedding(query_input):
    """ Get the results of the query using the best frame embedding """
    query_embedding = embeddings_processing.generate_query_embeddings(query_input, embedder)
    search_results = opensearch.knn_query_best(query_embedding.tolist(), N_RESULTS)
    return set_query_results(search_results, query_input)


def query_annotations_embeddings(query_input):
    """ Get the results of the query using the annotations embeddings """
    query_embedding = embeddings_processing.generate_query_embeddings(query_input, embedder)
    search_results = opensearch.knn_query_annotations(query_embedding.tolist(), N_RESULTS)
    return set_query_results(search_results, query_input)


def query_thesaurus(video_id, annotation_id):
    """ Get the results of querying for a similar sign """
    with open(os.path.join(EMBEDDINGS_PATH, "average_frame_embeddings.json.embeddings"), "rb") as f:
        average_frame_embeddings = pickle.load(f)
    embedding = average_frame_embeddings[video_id][annotation_id].tolist()
    search_results = opensearch.knn_query_average(embedding, N_RESULTS)
    return set_query_results(search_results)


def set_query_results(search_results, query_input=None):
    """ Set the info of the query from the search results """
    query_results = {}

    videos_annotations = {}

    for hit in search_results['hits']['hits']:
        video_id = hit['_source']['video_id']
        annotation_id = hit['_source']['annotation_id']

        if video_id not in query_results:
            query_results[video_id] = {}
            with open(os.path.join(ANNOTATIONS_PATH, f"{video_id}.json"), "r") as f:
                videos_annotations[video_id] = json.load(f)

        query_results[video_id][annotation_id] = {}
        query_results[video_id][annotation_id]['video_id'] = video_id
        query_results[video_id][annotation_id]['similarity_score'] = hit['_score']

        for annotation in videos_annotations[video_id][FACIAL_EXPRESSIONS_ID]["annotations"]:
            if annotation["annotation_id"] == annotation_id:
                query_results[video_id][annotation_id]['annotation_value'] = annotation['value']
                query_results[video_id][annotation_id]['start_time'] = annotation['start_time']
                query_results[video_id][annotation_id]['end_time'] = annotation['end_time']
                query_results[video_id][annotation_id]['phrase'] = annotation['phrase']
                query_results[video_id][annotation_id]['user_rating'] = annotation['user_rating']
                break

    if query_input:
        print_performance_metrics(query_results, query_input)

    return query_results


def query_true_expression(query_input):
    """ Get the results of the query using the ground truth """
    query_results = {}
    search_mode = session.get('search_mode', 1)
    pattern = re.compile(r'(^|\[|_|]|\(|-|\s){}($|\]|_|(?=\W)|\)|-|\s)'.format(query_input.lower()), re.IGNORECASE)
    with open(os.path.join(EMBEDDINGS_PATH, "average_frame_embeddings.json.embeddings"), "rb") as f:
        average_frame_embeddings = pickle.load(f)

    for video in os.listdir(os.path.join(FRAMES_PATH, search_mode)):
        with open(os.path.join(ANNOTATIONS_PATH, f"{video}.json"), "r") as f:
            video_annotations = json.load(f)
            if search_mode in video_annotations:
                for annotation in video_annotations[search_mode]["annotations"]:
                    if annotation["value"] is not None and pattern.search(annotation["value"]):
                        if video not in query_results:
                            query_results[video] = {}
                        query_results[video][annotation["annotation_id"]] = {}
                        query_results[video][annotation["annotation_id"]]['annotation_value'] = annotation["value"]
                        query_results[video][annotation["annotation_id"]]['start_time'] = annotation["start_time"]
                        query_results[video][annotation["annotation_id"]]['end_time'] = annotation["end_time"]
                        if search_mode == FACIAL_EXPRESSIONS_ID:
                            query_results[video][annotation["annotation_id"]]['phrase'] = annotation["phrase"]
                        query_results[video][annotation["annotation_id"]]['similarity_score'] = "N/A"

    return query_results


def print_performance_metrics(query_results, query_input):
    """ Print the performance metrics of the query
        Precision tells how many retrieved results were right
        Recall tells how many right results were retrieved
        F1 score is the harmonic mean of precision and recall """
    compare_results = query_true_expression(query_input)

    # Initialize counters for true positives, false positives and false negatives
    tp = 0  # True positives - number of annotations that were correctly retrieved
    fp = 0  # False positives - number of annotations that were retrieved but are not in the ground truth
    fn = 0  # False negatives - number of annotations that are in the ground truth but were not retrieved

    # Iterate over each video in query_results
    for video in query_results.keys():
        query_annotations = query_results[video].keys()

        # If the video is also in compare_results
        if video in compare_results:
            compare_annotations = compare_results[video].keys()

            # Count the number of true positives, false positives and false negatives
            tp += len(set(query_annotations).intersection(compare_annotations))
            fp += len(set(query_annotations).difference(compare_annotations))
            fn += len(set(compare_annotations).difference(query_annotations))
        else:
            # If the video is not in compare_results, all annotations are false positives
            fp += len(query_annotations)

    # Add the false negatives for videos only in compare_results
    for video, compare_annotations in compare_results.items():
        if video not in query_results:
            fn += len(compare_annotations)

    # Calculate precision, recall and F1 score
    precision = round(tp / (tp + fp), 2) if tp + fp > 0 else 0.0
    recall = round(tp / (tp + fn), 2) if tp + fn > 0 else 0.0
    f1 = round(2 * (precision * recall) / (precision + recall), 2) if precision + recall > 0 else 0.0

    print("-------------------------------------")
    print("-------------------------------------")
    print("Precision: ", precision)
    print("Recall: ", recall)
    print("F1: ", f1)
    print("-------------------------------------")
    print("-------------------------------------")


def get_frames_to_display(frames):
    """ Get the frames to display """
    frames_to_display = {}

    # Display only #num_frames_to_display frames of each expression
    for expression, all_frames in frames.items():

        # Calculate the step size
        if len(all_frames) <= N_FRAMES_TO_DISPLAY:
            step_size = 1
        else:
            step_size = (len(all_frames) - 1) // N_FRAMES_TO_DISPLAY + 1

        # Select frames to display
        frames_to_display[expression] = all_frames[::step_size]

        # Ensure that only num_frames_to_display frames are selected
        frames_to_display[expression] = frames_to_display[expression][:N_FRAMES_TO_DISPLAY]

    return frames_to_display

