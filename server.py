from flask import Flask, request, jsonify
from pyngrok import ngrok
from flask_cors import CORS
from PIL import Image
import base64
import os
import io
import subprocess
import time
import re
import requests
import firebase_admin
from firebase_admin import credentials, firestore, storage
import threading
import time
import subprocess
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, unquote
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, os.getenv("UPLOAD_FOLDER", "uploads"))
printer_name = os.getenv("PRINTER_NAME", "CanonCP1000")

def enable_printer():
    """Starting server.py, enabling printer"""
    try:
        print(f"🔄 Enabling printer: {printer_name}...")
        # cupsenable 명령어 실행
        subprocess.run(["cupsenable", printer_name], check=True)
        print(f"✅ Printer '{printer_name}' enabled successfully.")
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Failed to enable printer (Command Error): {e}")
    except Exception as e:
        print(f"⚠️ Failed to enable printer (Unexpected Error): {e}")

def get_job_status(job_id):
    """CUPS ?? ??? ??"""
    try:
        result = subprocess.run(['lpstat', '-W', 'completed', '-o'], 
                              capture_output=True, text=True, timeout=5)
        
        # ??? ?????? ??
        if str(job_id) in result.stdout and 'completed' in result.stdout.lower():
            return 'completed', None
        
        # ?? ?? ?? ??
        result = subprocess.run(['lpstat', '-o'], 
                              capture_output=True, text=True, timeout=5)
        
        if str(job_id) not in result.stdout:
            # ??? ??? ??? ??? ??? ??
            return 'completed', None
            
        return 'processing', None
        
    except Exception as e:
        return 'unknown', str(e)

def reboot_pi():
    try:
        subprocess.run(["sudo", "reboot"], check=True)
        print("? Raspberry Pi is rebooting...")
        return True, "Successfully"
    except subprocess.CalledProcessError as e:
        print(f"? Reboot failed: {e}")
        return False, "Reboot failed: {e}"

def clear_cups_jobs(restart=False):
    """
    Clears all print jobs from CUPS.
    
    Args:
        restart (bool): If True, restarts the CUPS service after clearing jobs.
    """
    try:
        # Cancel all print jobs
        subprocess.run(["cancel", "-a"], check=True)
        print("? All CUPS print jobs have been cleared.")
        
        if restart:
            # Restart the CUPS service (requires sudo privileges)
            subprocess.run(["sudo", "systemctl", "restart", "cups"], check=True)
            print("? CUPS service restarted successfully.")
        return True, "Successfully"
    except subprocess.CalledProcessError as e:
        print(f"? Command failed: {e}")
        return False, str(e)
    except FileNotFoundError:
        return False, "CUPS is not installed. Please check again"

@app.route('/check-status', methods=['GET'])
def check_status():
    printer_ok, printer_status =  check_printer_status(printer_name)
    return jsonify({
        'status': printer_status,
    }), 200

def check_printer_status(printer_name):
    try:
        result = subprocess.check_output(
            ["lpstat", "-p", printer_name],
            stderr=subprocess.STDOUT
        ).decode().lower()
        print(result)

        if "printing " in result:
            return False, "Printing"
        if "idle" in result:
            return True, "Idle"
        if "disabled" in result:
            return False, "Disabled"

        return False, "Unknown status"

    except subprocess.CalledProcessError as e:
        return False, e.output.decode()

def monitor_print_job(job_id, printer_name, timeout=60):
    """??? ??? ?????? ?? ??"""
    return True, ''
    

@app.route('/')
def home():
    return "? Raspberry Pi Photo Print Server is running."

@app.route('/upload', methods=['POST'])
def upload_image():
    data = request.json
    if not data or 'image' not in data:
        return jsonify({'error': 'No image data provided'}), 400
    
    try:
        # ??? ?? ?? ??
        printer_ok, printer_status = check_printer_status(printer_name)
        if not printer_ok:
            error_messages = {
                'ink_empty': '?? ???? ??????',
                'paper_empty': '??? ????',
                'printer_disabled': '???? ?????? ????'
            }
            return jsonify({
                'error': error_messages.get(printer_status, printer_status),
                'status': 'printer_error',
                'detail': printer_status
            }), 503
        
        # Decode base64 image
        image_data = base64.b64decode(data['image'])
        input_image = Image.open(io.BytesIO(image_data))
        
        # 4x6 inch ?? ?? (300 DPI ??)
        required_width = 1200
        required_height = 1800
        
        print(f"?? ??? ??: {input_image.width} x {input_image.height}")
        print(f"??? ??: {required_width} x {required_height}")
        #if input_image.width != required_width or input_image.height != required_height:
        #    error_msg = f"??? ??? ?? ????. ??: {input_image.width}x{input_image.height}, ??: {required_width}x{required_height}"
        #    print(error_msg)
        #    return jsonify({'error': error_msg}), 400
        
        print("??? ??? ??? - ?? ??")
        
        # RGB ??? ??
        if input_image.mode != 'RGB':
            if input_image.mode == 'RGBA':
                rgb_image = Image.new('RGB', input_image.size, (255, 255, 255))
                rgb_image.paste(input_image, mask=input_image.split()[3])
                final_image = rgb_image
            else:
                final_image = input_image.convert('RGB')
        else:
            final_image = input_image
        
        # Save as JPEG
        output_path = os.path.join(UPLOAD_FOLDER, 'print_image.jpg')
        final_image.save(output_path, 'JPEG', quality=100, dpi=(300, 300))
        
        print(f"?? ??? ?? ??: {final_image.width} x {final_image.height}")

        # ??? ?? ??
        result = subprocess.run([
            "lp",
            "-d", printer_name,
            "-o", "StpBorderless=True",
            "-o", "media=4x6",
            "-o", "scaling=100",
            output_path
        ], capture_output=True, text=True)

        if result.returncode != 0:
            return jsonify({
                'error': 'Failed to submit print job',
                'detail': result.stderr.strip(),
                'stdout': result.stdout.strip()
            }), 500
        
        # Job ID ??
        job_id = None
        match = re.search(r'request id is (\S+)-(\d+)', result.stdout)
        if match:
            job_id = f"{match.group(1)}-{match.group(2)}"
        else:
            match = re.search(r'(\d+)', result.stdout)
            if match:
                job_id = match.group(1)
        
        if not job_id:
            return jsonify({
                'error': 'Could not extract job ID',
                'stdout': result.stdout
            }), 500
        
        print(f"??? ?? ??? - Job ID: {job_id}")
        
        # ?? ????
        success, status = monitor_print_job(job_id, printer_name, timeout=120)
        
        if success:
            return jsonify({
                'message': 'Image printed successfully',
                'status': 'completed',
                'job_id': job_id
            }), 200
        else:
            error_messages = {
                'ink_empty': '??? ? ?? ???? ?????',
                'paper_empty': '??? ? ??? ??????',
                'printer_disabled': '??? ? ???? ?????????',
                'timeout': '??? ?? ?? ??'
            }
            return jsonify({
                'error': error_messages.get(status, f'Print failed: {status}'),
                'status': 'failed',
                'detail': status,
                'job_id': job_id
            }), 500

    except Exception as e:
        return jsonify({
            'error': str(e),
            'status': 'exception'
        }), 500

@app.route('/status', methods=['GET'])
def printer_status():
    """??? ?? ?? ?????"""
    printer_ok, status = check_printer_status(printer_name)
    
    return jsonify({
        'printer': printer_name,
        'ready': printer_ok,
        'status': status
    }), 200 if printer_ok else 503

@app.route('/reset-printer', methods=['GET'])
def reset_printer():
    success, status = clear_cups_jobs(restart=True)
    return jsonify({
        'ready': success,
        'status': status
    }), 200 if success else 503

@app.route('/reboot', methods=['GET'])
def reboot():
    success, status = reboot_pi()
    
    return jsonify({
        'ready': success,
        'status': status
    }), 200 if success else 503

@app.route('/check-connection', methods=['GET'])
def check_connection():
    return jsonify({
        'status': "Online"
    }), 200


def delete_storage_file_by_url(image_url):
    """Delete a Firebase Storage object using its gs:// or download URL."""
    if not image_url:
        return False, "empty_url"

    try:
        if image_url.startswith("gs://"):
            parsed = urlparse(image_url)
            bucket_name = parsed.netloc
            blob_path = parsed.path.lstrip("/")
        else:
            parsed = urlparse(image_url)
            path = parsed.path

            # Expected download URL format:
            # /v0/b/{bucket}/o/{encoded_object_path}
            marker = "/o/"
            if not path.startswith("/v0/b/") or marker not in path:
                return False, "unsupported_url_format"

            prefix, encoded_blob_path = path.split(marker, 1)
            prefix_parts = prefix.split("/")
            if len(prefix_parts) < 4:
                return False, "unsupported_url_format"

            bucket_name = prefix_parts[3]
            blob_path = unquote(encoded_blob_path)

        if not bucket_name or not blob_path:
            return False, "invalid_bucket_or_path"

        bucket = storage.bucket(bucket_name)
        blob = bucket.blob(blob_path)

        if not blob.exists():
            return True, "not_found"

        blob.delete()
        return True, "deleted"

    except Exception as e:
        return False, str(e)


def process_tasks():
    while True:
        try:
            print("? Checking for new tasks...")
            tasks_ref = fs.collection("Task")
            initial_tasks = tasks_ref.where("device_id", "==", device_id).where("status", "==", "Initial").get()
            
            downloaded_tasks_ids = []

            for task in initial_tasks:
                print(f"? Found task {task.id}")
                task_id = task.id
                task_data = task.to_dict()
                image_url = task_data.get("image_url")
                print(f"? Processing task {task_id} with image_url: {image_url}")

                if not image_url:
                    print(f"? Task {task_id} has no image_url. Skipping.")
                    continue

                if not os.path.exists(UPLOAD_FOLDER):
                    os.makedirs(UPLOAD_FOLDER)

                try:
                    response = requests.get(image_url, stream=True)
                    response.raise_for_status()

                    filename = image_url.split('/')[-1].split('?')[0]
                    filename = requests.utils.unquote(filename)
                    filename = os.path.basename(filename)
                    filepath = os.path.join(UPLOAD_FOLDER, filename)

                    with open(filepath, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    print(f"? Downloaded image {filename} for task {task_id}")

                    # Update status to downloaded
                    fs.collection("Task").document(task_id).update({"status": "Downloaded"})
                    downloaded_tasks_ids.append(task_id)
                    
                    print(f"? Updated task {task_id} status to Downloaded")

                except requests.exceptions.RequestException as e:
                    print(f"? Failed to download image for task {task_id}: {e}")
                except Exception as e:
                    print(f"? Error processing task {task_id}: {e}")

            # Print downloaded files
            print("? Checking for downloaded tasks to print...")
            downloaded_tasks_query = fs.collection("Task").where("device_id", "==", device_id).where("status", "==", "Downloaded").get()
            
            # Sort tasks by filename derived from image_url
            downloaded_tasks = sorted(
                downloaded_tasks_query,
                key=lambda task: os.path.basename(requests.utils.unquote(task.to_dict().get("image_url", "").split('/')[-1].split('?')[0]))
            )

            for task in downloaded_tasks:
                task_id = task.id
                task_data = task.to_dict()
                image_url = task_data.get("image_url")

                filename = image_url.split('/')[-1].split('?')[0]
                filename = requests.utils.unquote(filename)
                filename = os.path.basename(filename)
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                
                print(f"? Printing task {task_id} with image {filepath}")

                if os.path.exists(filepath):
                    try:
                        result = subprocess.run(
                            [
                                "lp",
                                "-d", printer_name,
                                "-o", "StpBorderless=True",
                                "-o", "media=4x6",
                                "-o", "scaling=100",
                                filepath
                            ],
                            capture_output=True,
                            text=True
                        )

                        if result.returncode == 0:
                            print(f"? Submitted print job for task {task_id}")
                            fs.collection("Task").document(task_id).update({
                                "status": "Printed",
                                "print_time": firestore.SERVER_TIMESTAMP,
                            })
                            os.remove(filepath)
                            print(f"? Removed image {filename} for task {task_id}")
                            print(f"? Waiting 30 seconds before processing next task")
                            time.sleep(30)
                        else:
                            print(f"? Failed to print image for task {task_id}: {result.stderr.strip()}")

                    except Exception as e:
                        print(f"? Error printing task {task_id}: {e}")

            # Cleanup: after 1 day from print_time, remove image_url and mark as deleted
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=1)
            printed_expired_tasks = (
                fs.collection("Task")
                .where("device_id", "==", device_id)
                .where("status", "==", "Printed")
                .where("print_time", "<=", cutoff_time)
                .get()
            )

            printed_without_time_tasks = (
                fs.collection("Task")
                .where("device_id", "==", device_id)
                .where("status", "==", "Printed")
                .where("print_time", "==", None)
                .get()
            )

            cleanup_tasks = {task.id: task for task in printed_expired_tasks}
            cleanup_tasks.update({task.id: task for task in printed_without_time_tasks})

            for task in cleanup_tasks.values():
                task_id = task.id
                task_data = task.to_dict()
                image_url = task_data.get("image_url")

                try:
                    deleted_ok, delete_status = delete_storage_file_by_url(image_url)
                    if not deleted_ok:
                        print(f"? Failed storage delete for task {task_id}: {delete_status}")
                        # Keep task as Printed to retry deletion on next cycle.
                        continue

                    fs.collection("Task").document(task_id).update({
                        "image_url": firestore.DELETE_FIELD,
                        "status": "deleted",
                    })
                    print(
                        f"? Cleared image_url and marked task {task_id} as deleted "
                        f"(storage: {delete_status})"
                    )
                except Exception as e:
                    print(f"? Failed cleanup for task {task_id}: {e}")
            
        except Exception as e:
            print(f"? An error occurred in the task processing loop: {e}")
        
        time.sleep(60)


service_account_path = os.getenv("SERVICE_ACCOUNT_PATH", "serviceAccountKey.json")
cred = credentials.Certificate(service_account_path)
firebase_admin.initialize_app(cred)
fs = firestore.client()
device_id = os.getenv("DEVICE_ID", "CikG4JrgaSVMpgYv4nqF")

def update_ip_to_firestore(ip):
    fs.collection("Device").document(device_id).set({
        "raspberry": {
            "ipAddress": ip
        }
    }, merge=True)
    
def sync_ip():
    ip = get_internal_ip()
    if ip:
        update_ip_to_firestore(ip)


def get_internal_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Doesn't actually send data
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None

def periodic_sync():
    while True:
        sync_ip()
        time.sleep(600)  # every 10 minutes

# threading.Thread(target=periodic_sync, daemon=True).start()


@app.route("/set-wifi", methods=["POST"])
def set_wifi():
    data = request.get_json()
    ssid = data.get("ssid")
    password = data.get("password")

    if not ssid or not password:
        return jsonify({"error": "Missing SSID or password"}), 400

    try:
        subprocess.run(
            ["sudo", "nmcli", "dev", "wifi", "connect", ssid, "password", password],
            check=True
        )
        return jsonify({"status": "WiFi updated"})
    except subprocess.CalledProcessError as e:
        return jsonify({"error": str(e)}), 500

def update_firestore_with_retry(internal_ip, public_url):
    while True:
        try:
            fs.collection("Device").document(device_id).set({
                "raspberry": {
                    "ipAddress": internal_ip,
                    "url": public_url
                }
            }, merge=True)

            print("? Firestore updated successfully")
            break  # stop retrying once successful

        except Exception as e:
            print("? Firestore update failed, retrying in 60 seconds...")
            print(e)
            time.sleep(60)

def main():

    # Printer enabling
    enable_printer()
    port = 5000
    internal_ip = get_internal_ip()
    public_url = ""

    # Try ngrok
    # try:
    #     tunnel = ngrok.connect(port)
    #     public_url = tunnel.public_url
    #     print(f"? Ngrok URL: {public_url}")
    # except Exception as e:
    #     print("?? Ngrok unavailable")
    #     print(e)

    # # Start Firestore retry in background
    # threading.Thread(
    #     target=update_firestore_with_retry,
    #     args=(internal_ip, public_url),
    #     daemon=True
    # ).start()

    # Start the task processing thread
    threading.Thread(target=process_tasks, daemon=True).start()

    # Start Flask server
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    main()

