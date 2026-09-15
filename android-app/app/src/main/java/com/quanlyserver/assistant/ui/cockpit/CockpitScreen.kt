package com.quanlyserver.assistant.ui.cockpit

import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext

/**
 * 2.5D Multi-Entity Spatial Depth & Living Character Cockpit Screen.
 * Genuine multi-layer spatial depth with zero static image facade:
 * - Plane 1: Deep space starfield generator (k = 0.05).
 * - Plane 2: Inpainted cockpit spaceship architecture (k = 0.18).
 * - Plane 3: Pulsing cybernetic floor rune energy circuit (k = 0.35).
 * - Plane 4: Living AI Character Entity with independent breathing, gaze tracking, eye blinking (k = 0.55).
 * - Plane 5: 3D Holographic HUD displays floating in the foreground (k = 0.85).
 */
@Composable
fun CockpitScreen() {
    val context = LocalContext.current
    val parallaxController = remember { CyberneticParallaxController(context) }

    DisposableEffect(Unit) {
        parallaxController.start()
        onDispose { parallaxController.stop() }
    }

    val sensorOffset by parallaxController.offsetFlow.collectAsState()

    // Smooth Touch Dragging for LDPlayer mouse interaction
    var targetDragX by remember { mutableStateOf(0f) }
    var targetDragY by remember { mutableStateOf(0f) }
    var isDragging by remember { mutableStateOf(false) }

    val smoothDragX by animateFloatAsState(
        targetValue = targetDragX,
        animationSpec = spring(
            dampingRatio = Spring.DampingRatioMediumBouncy,
            stiffness = Spring.StiffnessLow
        ),
        label = "SmoothDragX"
    )

    val smoothDragY by animateFloatAsState(
        targetValue = targetDragY,
        animationSpec = spring(
            dampingRatio = Spring.DampingRatioMediumBouncy,
            stiffness = Spring.StiffnessLow
        ),
        label = "SmoothDragY"
    )

    // Combined Parallax Vector (Sensors + Mouse Dragging)
    val combinedParallaxX = (sensorOffset.roll * 1.5f) + smoothDragX
    val combinedParallaxY = (sensorOffset.pitch * 1.5f) + smoothDragY

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
            .pointerInput(Unit) {
                detectDragGestures(
                    onDragStart = { isDragging = true },
                    onDragEnd = {
                        isDragging = false
                        // Elastic spring back to center when user releases drag
                        targetDragX = 0f
                        targetDragY = 0f
                    },
                    onDragCancel = {
                        isDragging = false
                        targetDragX = 0f
                        targetDragY = 0f
                    }
                ) { change, dragAmount ->
                    change.consume()
                    targetDragX = (targetDragX + dragAmount.x * 0.15f).coerceIn(-55f, 55f)
                    targetDragY = (targetDragY + dragAmount.y * 0.15f).coerceIn(-40f, 40f)
                }
            }
    ) {
        // [Planes 1 - 3: Architectural Deep Space & Cockpit Hull & Rune Floor]
        SpatialBackgroundScene(
            parallaxOffsetX = combinedParallaxX,
            parallaxOffsetY = combinedParallaxY
        )

        // [Plane 4: Living Character Entity - Independent Graphic Entity]
        LivingCharacterEntity(
            parallaxOffsetX = combinedParallaxX,
            parallaxOffsetY = combinedParallaxY,
            isPointerDown = isDragging,
            pointerPosition = Offset(combinedParallaxX, combinedParallaxY)
        )

        // [Plane 5: 3D Holographic HUD System Floating in Foreground]
        HologramRadarOverlay(
            modifier = Modifier.graphicsLayer {
                translationX = combinedParallaxX * 0.85f
                translationY = combinedParallaxY * 0.85f
                cameraDistance = 12f * density
            }
        )
    }
}
