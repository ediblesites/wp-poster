<?php
/**
 * Plugin Name: Fax Service Meta Fields
 * Description: Registers custom meta fields for fax-service post type
 * Version: 1.0
 */

// Register meta fields for fax-service post type
add_action('init', function() {
    // Register 'price' meta field
    register_post_meta('fax-service', 'price', [
        'show_in_rest' => true,
        'single' => true,
        'type' => 'string',
        'description' => 'Service price',
    ]);
    
    // Register 'features' meta field  
    register_post_meta('fax-service', 'features', [
        'show_in_rest' => true,
        'single' => true,
        'type' => 'string',
        'description' => 'Service features',
    ]);
    
    // Add more fields as needed
    register_post_meta('fax-service', 'setup_fee', [
        'show_in_rest' => true,
        'single' => true,
        'type' => 'string',
    ]);
    
    register_post_meta('fax-service', 'monthly_limit', [
        'show_in_rest' => true,
        'single' => true,
        'type' => 'string',
    ]);
});