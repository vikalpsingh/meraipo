echo " building and restarting the pod"

docker compose down

docker compose up --build -d

docker compose ps

docker compose restart