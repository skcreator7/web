from quart import Quart, jsonify
import os

app = Quart(__name__)

@app.route('/')
async def home():
    return jsonify({"status": "healthy", "message": "SK4FiLM API is running"})

@app.route('/health')
async def health():
    return jsonify({"status": "healthy"})

@app.route('/api/health')
async def api_health():
    return jsonify({"status": "healthy"})

@app.route('/api/search')
async def api_search():
    query = "test"
    return jsonify({
        "status": "success",
        "query": query,
        "results": [
            {
                "type": "text",
                "content": f"Test result for: {query} - Backend is working!",
                "date": "2024-01-01T00:00:00"
            }
        ],
        "count": 1
    })

@app.route('/api/latest_posters')
async def api_latest_posters():
    return jsonify({
        "status": "success",
        "posters": [
            {
                "photo": "test_photo_1",
                "caption": "Test Movie 1 - Backend Working",
                "search_query": "Test Movie"
            }
        ],
        "count": 1
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)
