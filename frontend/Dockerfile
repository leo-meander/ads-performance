# Pulled through Google's Docker Hub mirror, not registry-1.docker.io: Zeabur's
# builders share an egress IP, so anonymous Docker Hub pulls hit the per-IP rate
# limit and the build dies with "429 Too Many Requests" on the base image alone.
# Same image, same tag — mirror.gcr.io is a transparent cache.
# Alternative if this mirror ever goes away: public.ecr.aws/docker/library/node:20-alpine
FROM mirror.gcr.io/library/node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

RUN npm run build

EXPOSE 3000

CMD ["npm", "start"]
