FROM node:22-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install --omit=dev

COPY server.js ./

EXPOSE 3003

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
    CMD node -e "fetch('http://127.0.0.1:3003/health').then(r => { if (!r.ok) process.exit(1) }).catch(() => process.exit(1))"

CMD ["npm", "start"]
