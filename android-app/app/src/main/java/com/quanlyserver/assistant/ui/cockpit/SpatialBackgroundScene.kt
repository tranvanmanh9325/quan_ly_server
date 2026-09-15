package com.quanlyserver.assistant.ui.cockpit

import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import com.quanlyserver.assistant.R
import kotlin.random.Random

/**
 * Spatial Background Scene: Renders the multi-plane architectural space environment:
 * 1. Deep space starfield generator with mathematical twinkle cycles.
 * 2. Inpainted architectural cockpit hull & panoramic planet window.
 * 3. Cybernetic rune circuit platform with pulsating harmonic energy waves.
 */
@Composable
fun SpatialBackgroundScene(
    modifier: Modifier = Modifier,
    parallaxOffsetX: Float,
    parallaxOffsetY: Float
) {
    // 1. Floor Rune Energy Wave Pulsing (2.4s cycle)
    val infiniteTransition = rememberInfiniteTransition(label = "RunePulseTransition")
    val runePulseAlpha by infiniteTransition.animateFloat(
        initialValue = 0.35f,
        targetValue = 0.95f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1400, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "RunePulseAlpha"
    )

    // 2. Starfield twinkling phase
    val starfieldTwinkle by infiniteTransition.animateFloat(
        initialValue = 0.3f,
        targetValue = 1.0f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 2800, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "StarfieldTwinkle"
    )

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(Color.Black)
    ) {
        // [Plane 1: Deep Space Twinkling Starfield]
        // Very low parallax factor (k = 0.05) to simulate infinite distance
        Canvas(
            modifier = Modifier
                .fillMaxSize()
                .graphicsLayer {
                    translationX = parallaxOffsetX * 0.05f
                    translationY = parallaxOffsetY * 0.05f
                }
        ) {
            val starCount = 65
            val seed = 42L
            val rng = Random(seed)

            for (i in 0 until starCount) {
                // Focus stars inside the panoramic window area (top 15% - 60%)
                val x = rng.nextFloat() * size.width
                val y = (rng.nextFloat() * 0.45f + 0.15f) * size.height
                val radius = rng.nextFloat() * 1.8f + 0.6f
                
                // Varied phase twinkling
                val individualAlpha = ((starfieldTwinkle + rng.nextFloat()) % 1.0f).coerceIn(0.2f, 1.0f)
                val starColor = if (i % 3 == 0) Color(0xFF00FFEA) else Color.White

                drawCircle(
                    color = starColor.copy(alpha = individualAlpha),
                    radius = radius,
                    center = Offset(x, y)
                )
            }
        }

        // [Plane 2: Inpainted Cockpit Architectural Hull & Space Window]
        // Medium parallax factor (k = 0.18) representing the spaceship structure
        Image(
            painter = painterResource(id = R.drawable.cockpit_background_clean),
            contentDescription = "Spaceship Cockpit Hull",
            contentScale = ContentScale.Crop,
            modifier = Modifier
                .fillMaxSize()
                .graphicsLayer {
                    translationX = parallaxOffsetX * 0.18f
                    translationY = parallaxOffsetY * 0.18f
                    cameraDistance = 16f * density
                }
        )

        // [Plane 3: Cybernetic Floor Rune Circuit Energy Waves]
        // Floor perspective parallax (k = 0.35) with pulsating cyan glow (no global color filter tint)
        Image(
            painter = painterResource(id = R.drawable.floor_rune_glow),
            contentDescription = "Pulsing Floor Rune Energy Circuit",
            contentScale = ContentScale.Crop,
            modifier = Modifier
                .fillMaxSize()
                .graphicsLayer {
                    translationX = parallaxOffsetX * 0.35f
                    translationY = parallaxOffsetY * 0.35f
                    alpha = runePulseAlpha
                }
        )
    }
}
