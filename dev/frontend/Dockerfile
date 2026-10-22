# Étape 1 : compilation de l'application (Node n'est pas dans l'image finale).
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Préfixes des appels du navigateur. Par défaut : même origine que la page, via le WAF.
# Ils sont figés à la construction (Vite) ; ne les changer que si le WAF route autrement.
ARG VITE_API_BASE=/api
ARG VITE_AUTH_BASE=/auth
# Reconnaissance faciale : VITE_FACE_MODE = api (service IA) | mock (simulation) | off (plan B global).
ARG VITE_FACE_MODE=mock
ARG VITE_FACE_BASE=/face
ENV VITE_API_BASE=$VITE_API_BASE VITE_AUTH_BASE=$VITE_AUTH_BASE \
    VITE_FACE_MODE=$VITE_FACE_MODE VITE_FACE_BASE=$VITE_FACE_BASE
RUN npm run build

# Étape 2 : fichiers statiques servis par nginx. Le WAF est devant (voir doc/ARCHITECTURE.md).
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/health || exit 1
