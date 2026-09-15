package com.quanlyserver.assistant.ui.cockpit

import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import kotlin.random.Random

data class StarParticle(val xRatio: Float, val yRatio: Float, val baseAlpha: Float, val radius: Float)

@Composable
fun TwinklingStarsOverlay(modifier: Modifier = Modifier) {
    val stars = remember {
        List(35) {
            StarParticle(
                xRatio = Random.nextFloat(),
                yRatio = Random.nextFloat() * 0.45f, // Only in upper space window area
                baseAlpha = Random.nextFloat() * 0.5f + 0.3f,
                radius = Random.nextFloat() * 1.8f + 0.8f
            )
        }
    }

    val infiniteTransition = rememberInfiniteTransition(label = "StarTwinkle")
    val twinklePulse by infiniteTransition.animateFloat(
        initialValue = 0.4f,
        targetValue = 1.0f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 2400, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "StarTwinklePulse"
    )

    Canvas(modifier = modifier.fillMaxSize()) {
        stars.forEach { s ->
            val center = Offset(size.width * s.xRatio, size.height * s.yRatio)
            val alpha = (s.baseAlpha * twinklePulse).coerceIn(0f, 1f)
            drawCircle(
                color = Color.White.copy(alpha = alpha),
                radius = s.radius,
                center = center
            )
        }
    }
}

@Composable
fun HologramRadarOverlay(modifier: Modifier = Modifier) {
    val infiniteTransition = rememberInfiniteTransition(label = "RadarSweep")
    
    // Continuous 360 degree rotation
    val sweepAngle by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 8000, easing = LinearEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "RadarRotation"
    )

    // Cyan energy pulse
    val pulseAlpha by infiniteTransition.animateFloat(
        initialValue = 0.35f,
        targetValue = 0.85f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1800, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "CyanEnergyPulse"
    )

    Canvas(modifier = modifier.fillMaxSize()) {
        // Hologram Radar on the right screen (around X=86%, Y=31%)
        val radarCenter = Offset(size.width * 0.855f, size.height * 0.315f)
        val radarRadius = size.width * 0.085f
        val cyanColor = Color(0xFF00E5FF).copy(alpha = pulseAlpha)

        // Rotating beam
        rotate(degrees = sweepAngle, pivot = radarCenter) {
            drawArc(
                color = cyanColor,
                startAngle = 0f,
                sweepAngle = 60f,
                useCenter = true,
                topLeft = Offset(radarCenter.x - radarRadius, radarCenter.y - radarRadius),
                size = Size(radarRadius * 2f, radarRadius * 2f)
            )
        }

        // Left Hologram "United AI System" subtle energy sweep line (around X=14%, Y=30%)
        val leftHudTop = size.height * 0.28f
        val leftHudBottom = size.height * 0.36f
        val leftHudX = size.width * 0.12f
        val leftHudW = size.width * 0.18f
        val scanY = leftHudTop + ((sweepAngle / 360f) * (leftHudBottom - leftHudTop))

        drawLine(
            color = Color(0xFF00F0FF).copy(alpha = pulseAlpha * 0.7f),
            start = Offset(leftHudX, scanY),
            end = Offset(leftHudX + leftHudW, scanY),
            strokeWidth = 1.5f
        )
    }
}

@Composable
fun RuneCircuitPulseOverlay(modifier: Modifier = Modifier) {
    val infiniteTransition = rememberInfiniteTransition(label = "RunePulse")
    val glowAlpha by infiniteTransition.animateFloat(
        initialValue = 0.25f,
        targetValue = 0.75f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 2600, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "RuneGlow"
    )

    Canvas(modifier = modifier.fillMaxSize()) {
        val runeCenter = Offset(size.width * 0.50f, size.height * 0.835f)
        val runeRadiusX = size.width * 0.14f
        val runeRadiusY = size.height * 0.045f
        val runeColor = Color(0xFF80D8FF).copy(alpha = glowAlpha)

        // Center hexagon / diamond rune floor subtle ambient glow
        drawOval(
            color = runeColor,
            topLeft = Offset(runeCenter.x - runeRadiusX, runeCenter.y - runeRadiusY),
            size = Size(runeRadiusX * 2f, runeRadiusY * 2f),
            style = Stroke(width = 2.0f)
        )
    }
}
