FROM maven:3.9.6-eclipse-temurin-21 AS builder
WORKDIR /app
COPY pom.xml .
RUN mvn dependency:go-offline -B
COPY src ./src
RUN mvn package -DskipTests -B

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
# Only tini (graceful shutdown) and wget (healthcheck) needed — Playwright/VNC moved to ai-agent-service
RUN apk add --no-cache tini wget
COPY --from=builder /app/target/metrics-service-0.0.1-SNAPSHOT.jar app.jar
EXPOSE 8082
ENTRYPOINT ["/sbin/tini", "--", "java", "-jar", "app.jar"]
