import io
import numpy as np
import torch

from .sentence_embeddings import Embedder as SentenceEmbedder
import os
import pickle
import gc

st = SentenceEmbedder()


def generate_frame_embeddings(frames_dir, result_dir):
    """ Generates facial expression frame embeddings for a folder of videos, choosing 4 frames
    equally spaced for each video. """
    print("Generating frame embeddings", flush=True)

    n_embeddings = 4
    embeddings = {}
    annotations_batch_size = 32

    embeddings_file = os.path.join(result_dir, 'frame_embeddings.json.embeddings')
    if os.path.exists(embeddings_file):
        with open(embeddings_file, 'rb') as f:
            embeddings = pickle.load(f)

    for video in os.listdir(frames_dir):

        if video in embeddings:
            continue

        print(f"Working on {video}", flush=True)

        video_dir = os.path.join(frames_dir, video)
        embeddings[video] = {}

        annotations_dir = os.listdir(video_dir)
        for i in range(0, len(annotations_dir), annotations_batch_size):
            annotations_batch = annotations_dir[i:i + annotations_batch_size]
            print(f"Working on annotations: {annotations_batch}", flush=True)

            for annotation in annotations_batch:
                expression_frames_dir = os.path.join(video_dir, annotation)
                annotation_embedding = None

                all_frames = os.listdir(expression_frames_dir)

                # Select #n_embeddings frames to generate embeddings
                if len(all_frames) <= n_embeddings:
                    step_size = 1
                else:
                    # Calculate the step size
                    step_size = (len(all_frames) - 1) // n_embeddings + 1

                frames_to_encode = all_frames[::step_size]
                frames_to_encode = frames_to_encode[:n_embeddings]

                for frame in frames_to_encode:
                    full_path = os.path.abspath(os.path.join(expression_frames_dir, frame))

                    if not os.path.isfile(full_path):
                        continue

                    # Initialize embeddings[video][annotation] as a zero tensor if it's not already initialized
                    if annotation_embedding is None:
                        annotation_embedding = torch.zeros_like(st.image_encode(full_path))

                    # generate embedding and sum it to the total embedding
                    annotation_embedding += st.image_encode(full_path)

                embeddings[video][annotation] = annotation_embedding

                del annotation_embedding
                torch.cuda.empty_cache()

            with open(embeddings_file, 'wb') as f:
                pickle.dump(embeddings, f)

            gc.collect()


def generate_average_and_best_frame_embeddings(frames_dir, result_dir):
    """ Generates the average and best facial expression frame embeddings of a video for a folder of videos """
    print("Generating average and best frame embeddings", flush=True)

    average_embeddings_file = os.path.join(result_dir, 'average_frame_embeddings.json.embeddings')
    best_embeddings_file = os.path.join(result_dir, 'best_frame_embeddings.json.embeddings')
    annotations_batch_size = 8
    average_embeddings = {}
    best_embeddings = {}

    if os.path.exists(average_embeddings_file):
        with open(average_embeddings_file, 'rb') as f:
            average_embeddings = pickle.load(f)

    if os.path.exists(best_embeddings_file):
        with open(best_embeddings_file, 'rb') as f:
            best_embeddings = pickle.load(f)

    for video in os.listdir(frames_dir):

        if video in average_embeddings and video in best_embeddings:
            continue

        print(f"Working on {video}", flush=True)
        video_dir = os.path.join(frames_dir, video)
        average_embeddings[video] = {}
        best_embeddings[video] = {}

        annotations_dir = os.listdir(video_dir)
        for i in range(0, len(annotations_dir), annotations_batch_size):
            annotations_batch = annotations_dir[i:i + annotations_batch_size]

            for annotation in annotations_batch:
                expression_frames_dir = os.path.join(video_dir, annotation)
                total_embedding = None
                best_embedding = None
                best_score = -1
                frame_count = 0

                for frame in os.listdir(expression_frames_dir):
                    full_path = os.path.abspath(os.path.join(expression_frames_dir, frame))

                    if not os.path.isfile(full_path):
                        continue

                    with torch.no_grad():  # Avoid storing computations for gradient calculation
                        current_embedding = st.image_encode(full_path)

                    # calculate score based on the norm (or length) of the embedding vector
                    # the higher the norm, more intense and distinct the expression is, the better the embedding
                    current_score = np.linalg.norm(current_embedding.detach().cpu().numpy())

                    if current_score > best_score:
                        best_score = current_score
                        best_embedding = current_embedding

                    if total_embedding is None:
                        total_embedding = current_embedding
                    else:
                        total_embedding += current_embedding
                    frame_count += 1

                # calculate average embedding
                if frame_count > 0:
                    average_embedding = total_embedding / frame_count
                    average_embeddings[video][annotation] = average_embedding

                best_embeddings[video][annotation] = best_embedding

                del total_embedding, best_embedding
                torch.cuda.empty_cache()

            with open(average_embeddings_file, 'wb') as f:
                pickle.dump(average_embeddings, f)

            with open(best_embeddings_file, 'wb') as f:
                pickle.dump(best_embeddings, f)

            gc.collect()


def generate_query_embeddings(query_input):
    """ Generate the user queries embeddings """
    return st.text_encode(query_input.lower())
