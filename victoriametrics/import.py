import json
import pathlib
import requests

# Configuration
VM_IMPORT_URL = "http://localhost:8428/api/v1/import"
JSON_FILE_PATH = "import.json"
BATCH_SIZE = 1000  # Number of data points per HTTP request


def import_json_to_victoriametrics(file_path: str, import_url: str):
    path = pathlib.Path(file_path)

    if not path.exists():
        print(f"Error: File '{file_path}' not found.")
        return

    print(f"Reading data from {file_path}...")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Ensure data is a list of data points
    if isinstance(data, dict):
        data_points = [data]
    elif isinstance(data, list):
        data_points = data
    else:
        print("Error: JSON content must be an object or a list of objects.")
        return

    total_points = len(data_points)
    print(
        f"Loaded {total_points} data points. Starting import in batches of {BATCH_SIZE}..."
    )

    # Stream in batches
    for i in range(0, total_points, BATCH_SIZE):
        batch = data_points[i : i + BATCH_SIZE]

        # Convert the batch into NDJSON (Newline Delimited JSON)
        payload = "\n".join([json.dumps(dp) for dp in batch]) + "\n"

        response = requests.post(
            import_url,
            data=payload.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

        if response.status_code == 204 or response.status_code == 200:
            print(
                f"Successfully imported points {i + 1} to {min(i + BATCH_SIZE, total_points)} / {total_points}"
            )
        else:
            print(f"Failed batch {i // BATCH_SIZE + 1}: Status {response.status_code}")
            print(f"Response: {response.text}")
            break


if __name__ == "__main__":
    import_json_to_victoriametrics(JSON_FILE_PATH, VM_IMPORT_URL)
