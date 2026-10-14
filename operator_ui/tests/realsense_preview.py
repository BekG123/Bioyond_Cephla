"""Full console browser QA on port 5004: fake robot, real isolated depth worker."""
from preview_server import app
from realsense_service import register_realsense

register_realsense(app)

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5004, threaded=True)
