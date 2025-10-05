from flask import Flask, jsonify, request
import os

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({'message': 'Railway Flask App is running!', 'status': 'ok', 'version': '4.0'})

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'message': 'Flask app is working'})

@app.route('/test')
def test():
    return jsonify({'message': 'Test route is working!', 'routes': ['/health', '/save_polygon']})

@app.route('/save_polygon', methods=['POST'])
def save_polygon():
    try:
        data = request.json
        return jsonify({
            'message': 'Polygon saved successfully',
            'data_received': data is not None,
            'status': 'success'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=True)
