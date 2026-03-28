package com.miniserver.dashboard.config;

import org.springframework.context.annotation.Configuration;

import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class CorsConfig implements WebMvcConfigurer {

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        // allowedHeaders("*") + allowCredentials(true) vi phạm CORS spec:
        // browser sẽ reflect toàn bộ request headers thay vì chặn → quá rộng.
        // Chỉ khai báo các header thực sự cần thiết.
        registry.addMapping("/**")
                .allowedOrigins("http://localhost:5173", "http://127.0.0.1:5173")
                .allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS")
                .allowedHeaders("Content-Type", "Accept", "Authorization", "X-Requested-With")
                .allowCredentials(true)
                .maxAge(3600); // Cache preflight 1 giờ, giảm OPTIONS request
    }
}

