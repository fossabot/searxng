/*jshint esversion: 6 */

module.exports = function(grunt) {

  const path = require('path');

  grunt.initConfig({
    pkg: grunt.file.readJSON('package.json'),
    watch: {
      scripts: {
        files: ['src/**'],
        tasks: ['eslint', 'copy', 'concat', 'uglify', 'less:development', 'less:production']
      }
    },
    eslint: {
      options: {
        configFile: '.eslintrc.json',
        failOnError: false
      },
      target: [
        'src/js/main/*.js',
        'src/js/head/*.js',
        '../__common__/js/*.js'
      ],
    },
    stylelint: {
      options: {
        formatter: 'unix',
      },
      src: [
        'src/less/**/*.less',
      ]
    },
    copy: {
      js: {
        expand: true,
        cwd: './node_modules',
        dest: './js/',
        flatten: true,
        filter: 'isFile',
        timestamp: true,
        src: [
          './leaflet/dist/leaflet.js',
        ]
      },
      css: {
        expand: true,
        cwd: './node_modules',
        dest: './css/',
        flatten: true,
        filter: 'isFile',
        timestamp: true,
        src: [
          './leaflet/dist/leaflet.css',
        ]
      },
      leaflet_images: {
        expand: true,
        cwd: './node_modules',
        dest: './css/images/',
        flatten: true,
        filter: 'isFile',
        timestamp: true,
        src: [
          './leaflet/dist/images/*.png',
        ]
      },
    },
    concat: {
      head_and_body: {
        options: {
          separator: ';'
        },
        files: {
          'js/searxng.head.js': ['src/js/head/*.js'],
          'js/searxng.js': ['src/js/main/*.js', '../__common__/js/*.js', './node_modules/autocomplete-js/dist/autocomplete.js']
        }
      }
    },
    uglify: {
      options: {
        output: {
	        comments: 'some'
        },
        ie8: false,
        warnings: true,
        compress: false,
        mangle: true,
        sourceMap: true
      },
      dist: {
        files: {
          'js/searxng.head.min.js': ['js/searxng.head.js'],
          'js/searxng.min.js': ['js/searxng.js']
        }
      }
    },
    less: {
      development: {
        options: {
          paths: ["less"],
        },
        files: {
          "css/searxng.css": "src/less/style.less",
          "css/searxng-rtl.css": "src/less/style-rtl.less"
        }
      },
      production: {
        options: {
          paths: ["less"],
          plugins: [
            new (require('less-plugin-clean-css'))()
          ],
          sourceMap: true,
          sourceMapURL: (name) => { const s = name.split('/'); return s[s.length - 1] + '.map';},
          outputSourceFiles: false,
          sourceMapRootpath: '../',
        },
        files: {
          "css/searxng.min.css": "src/less/style.less",
          "css/searxng-rtl.min.css": "src/less/style-rtl.less"
        }
      },
    },
    svg2jinja: {
      all: {
        src: {
          'error': 'node_modules/ionicons/dist/svg/alert-circle.svg',
          'warning': 'node_modules/ionicons/dist/svg/alert-circle-outline.svg',
          'close-outline': 'node_modules/ionicons/dist/svg/close-outline.svg',
          'chevron-up': 'node_modules/ionicons/dist/svg/chevron-up-outline.svg',
          'menu': 'node_modules/ionicons/dist/svg/menu-outline.svg',
          'ellipsis-vertical': 'node_modules/ionicons/dist/svg/ellipsis-vertical-outline.svg',
          'magnet': 'node_modules/ionicons/dist/svg/magnet-outline.svg',
          'globe': 'node_modules/ionicons/dist/svg/globe-outline.svg',
          'search-outline': 'node_modules/ionicons/dist/svg/search-outline.svg',
          'image': 'node_modules/ionicons/dist/svg/image-outline.svg',
          'play': 'node_modules/ionicons/dist/svg/play-outline.svg',
          'newspaper': 'node_modules/ionicons/dist/svg/newspaper-outline.svg',
          'location': 'node_modules/ionicons/dist/svg/location-outline.svg',
          'musical-notes': 'node_modules/ionicons/dist/svg/musical-notes-outline.svg',
          'layers': 'node_modules/ionicons/dist/svg/layers-outline.svg',
          'school': 'node_modules/ionicons/dist/svg/school-outline.svg',
          'file-tray-full': 'node_modules/ionicons/dist/svg/file-tray-full-outline.svg',
          'people': 'node_modules/ionicons/dist/svg/people-outline.svg',
        },
        dest: '../../../templates/simple/icons.html'  
      },
    },
  });


  grunt.registerMultiTask('svg2jinja', 'Create Jinja2 macro', function() {
    const ejs = require('ejs');
    const icons = {}
    for(const iconName in this.data.src) {
        const svgFileName = this.data.src[iconName];
        try {
            icons[iconName] = grunt.file.read(svgFileName, { encoding: 'utf8' })
        } catch (err) {
            console.error(err)
        }
    }
    const template = `{%- set icons = {
      <% for (const iconName in icons) { %>  '<%- iconName %>':'<%- icons[iconName] %>',
      <% } %>
      } 
      -%}
      
      {% macro icon(action, alt) -%}
          <span class="ion-icon-big ion-{{ action }}" title="{{ alt }}">{{ icons[action] | safe }}</span>
      {%- endmacro %}
      
      {% macro icon_small(action) -%}
          <span class="ion-icon ion-{{ action }}" title="{{ alt }}">{{ icons[action] | safe }}</span>
      {%- endmacro %}
      `;
    const result = ejs.render(template, { icons });
    grunt.file.write(this.data.dest, result, { encoding: 'utf8' });
  });

  grunt.loadNpmTasks('grunt-contrib-watch');
  grunt.loadNpmTasks('grunt-contrib-copy');
  grunt.loadNpmTasks('grunt-contrib-uglify');
  grunt.loadNpmTasks('grunt-contrib-jshint');
  grunt.loadNpmTasks('grunt-contrib-concat');
  grunt.loadNpmTasks('grunt-contrib-less');
  grunt.loadNpmTasks('grunt-contrib-cssmin');
  grunt.loadNpmTasks('grunt-stylelint');
  grunt.loadNpmTasks('grunt-eslint');

  grunt.registerTask('test', ['jshint']);

  grunt.registerTask('default', [
    'eslint',
    'stylelint',
    'copy',
    'concat',
    'svg2jinja',
    'uglify',
    'less:development',
    'less:production'
  ]);
};
