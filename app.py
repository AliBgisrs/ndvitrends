from flask import Flask, render_template, request, send_file, jsonify, session
import os, uuid, zipfile
import fiona
import geopandas as gpd
from calculate_ndvi import calculate_stats

app = Flask(__name__)
app.secret_key = "ndvi_secret"
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

progress_store = {}

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        job_id = str(uuid.uuid4())
        session["job_id"] = job_id
        progress_store[job_id] = 0

        ndvi_files = request.files.getlist("ndvi_files")
        poly_file = request.files["poly_file"]
        plot_id = request.form["plot_id"]

        job_dir = os.path.join(UPLOAD_FOLDER, job_id)
        os.makedirs(job_dir, exist_ok=True)

        # Save NDVI rasters
        ndvi_paths = []
        for f in ndvi_files:
            path = os.path.join(job_dir, f.filename)
            f.save(path)
            ndvi_paths.append(path)

        # Save polygon file
        poly_path = os.path.join(job_dir, poly_file.filename)
        poly_file.save(poly_path)

        # If zipped shapefile/GDB -> unzip
        if poly_path.endswith(".zip"):
            with zipfile.ZipFile(poly_path, "r") as zip_ref:
                zip_ref.extractall(job_dir)
            for root, dirs, files in os.walk(job_dir):
                for d in dirs:
                    if d.endswith(".gdb"):
                        poly_path = os.path.join(root, d)
                        break
                for f in files:
                    if f.endswith(".shp"):
                        poly_path = os.path.join(root, f)
                        break

        # If GDB has multiple layers -> show layer selection
        if poly_path.endswith(".gdb"):
            layers = fiona.listlayers(poly_path)
            if len(layers) > 1:
                return render_template(
                    "select_layer.html",
                    layers=layers,
                    plot_id=plot_id,
                    poly_path=poly_path,
                    ndvi_files=ndvi_paths
                )

        # Run calculation directly
        return run_calculation(job_id, ndvi_paths, poly_path, plot_id)

    return render_template("index.html")


@app.route("/get_fields", methods=["POST"])
def get_fields():
    """Fetch polygon fields dynamically when user uploads shapefile/GDB"""
    poly_file = request.files["poly_file"]
    temp_path = os.path.join(UPLOAD_FOLDER, "temp_" + poly_file.filename)
    poly_file.save(temp_path)

    # Unzip if zip
    poly_path = temp_path
    if temp_path.endswith(".zip"):
        extract_dir = temp_path + "_unzipped"
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(temp_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)

        for root, dirs, files in os.walk(extract_dir):
            for d in dirs:
                if d.endswith(".gdb"):
                    poly_path = os.path.join(root, d)
                    break
            for f in files:
                if f.endswith(".shp"):
                    poly_path = os.path.join(root, f)
                    break

    # Read fields
    if poly_path.endswith(".gdb"):
        layers = fiona.listlayers(poly_path)
        gdf = gpd.read_file(poly_path, layer=layers[0])
    else:
        gdf = gpd.read_file(poly_path)

    fields = list(gdf.columns)

    # Cleanup
    try:
        os.remove(temp_path)
    except:
        pass

    return jsonify({"fields": fields})


def run_calculation(job_id, ndvi_paths, poly_path, plot_id, selected_layer=None):
    def update_progress(pct):
        progress_store[job_id] = pct

    output_file = calculate_stats(
        ndvi_paths, poly_path, plot_id,
        os.path.dirname(poly_path),
        progress_callback=update_progress,
        selected_layer=selected_layer
    )
    session["output_file"] = output_file
    return render_template("progress.html", job_id=job_id)


@app.route("/progress/<job_id>")
def progress(job_id):
    return jsonify({"progress": progress_store.get(job_id, 0)})


@app.route("/download")
def download():
    output_file = session.get("output_file")
    if output_file and os.path.exists(output_file):
        return send_file(output_file, as_attachment=True)
    return "No file found. Please run the tool again."


if __name__ == "__main__":
    app.run(debug=True)
