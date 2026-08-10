FROM maven:3.9.6-eclipse-temurin-21 AS builder
WORKDIR /app
COPY pom.xml .
RUN mvn dependency:go-offline -B
COPY src ./src
RUN mvn package -DskipTests -B

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
RUN apk add --no-cache wget chromium font-noto-emoji nss freetype harfbuzz ca-certificates ttf-freefont nodejs gcompat libc6-compat && \
    (ln -s /lib/libc.musl-x86_64.so.1 /lib/ld-linux-x86-64.so.2 || true)
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium
COPY --from=builder /app/target/metrics-service-0.0.1-SNAPSHOT.jar app.jar
EXPOSE 8082
ENTRYPOINT ["java", "-jar", "app.jar"]
