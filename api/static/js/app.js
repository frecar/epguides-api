
var ApiExample = React.createClass({

  getInitialState: function() {
     return {result: "loading ... ", limit:null};
  },

  componentDidMount: function() {
     this.queryEndpoint();
  },

  queryEndpoint: function() {
    let that = this;
    let url = this.props.endpoint.path;
    console.log(url);
    $.ajax({ url:url, 
      error:function (xhr, ajaxOptions, thrownError){
        console.log(xhr.responseJSON);
        this.setState({result: JSON.stringify(xhr.responseJSON)});
      }.bind(this)
   }).success(function(res){
        if(this.props.endpoint.limit) {
          res = res.slice(0, that.props.endpoint.limit);
        }
        this.setState({result: JSON.stringify(res, null, ' ')});
     }.bind(this));
  },

  render_curl_link: function() {
      return (
        <pre>
            <code className="bash hljs">
              <span className="hljs-meta">
              $ curl <a target="_blank"
                        href={this.props.endpoint.path}>
                          {this.props.endpoint.path}</a>
              </span>
            </code>
          </pre>
      );
  },

  render: function() {

    var results_comment = "";
    if(this.props.endpoint.limit) {
      results_comment = "Note: Number of results are limited to "
      + this.props.endpoint.limit + " in this example";
    }

    return (
      <section className="post">
        <header className="post-header">
            <h3 className="post-title">{this.props.endpoint.title}</h3>
        </header>
        <div className="post-description">  
          {this.render_curl_link()}
          <pre>
            <code className="json hljs">
              {this.state.result}
            </code>
          </pre>
          {results_comment}
        </div>
      </section>
    );
  }
});

var ApiRenderOverview = React.createClass({

  getInitialState() {
     return {examples: []};
  },

  componentDidMount() {
     this.fetchExamples();
  },

  fetchExamples() {
    let that = this;
    let url = "/api/examples/";
    $.ajax({ url:url}).success(function(res){
        this.setState({examples: res});
     }.bind(this));
  },

  renderLinkToReportIssues() {
    return (
      <a target="_blank" href="https://github.com/frecar/epguides-api/issues">
        report bugs and suggest new features
      </a>
    );
  },

  render() {
    return (
      <div id="layout" className="pure-g">
          <div className="sidebar pure-u-1 pure-u-md-1-4">
              <div className="header">
                  <h1 className="brand-title">epguides api</h1>
                  <h2 className="brand-tagline">TV Shows API</h2>
              </div>
          </div>
          <div className="content pure-u-1 pure-u-md-3-4">
            <div class="header">
              <h1>Welcome to Epguides API</h1>
              <p>
                This project aims to make it easier to query data about tvshows from epguides.com
                <br />
                Feel free to {this.renderLinkToReportIssues()}.
              </p>
            </div>
            <div className="posts" id="posts">
              {this.state.examples.map(function (item) {
                return <ApiExample key={item.path} endpoint={item} />;
              })}
            </div>
          </div>
      </div>
    );
  }
});

ReactDOM.render(
  <ApiRenderOverview />,
  document.getElementById('content')
);

hljs.initHighlightingOnLoad();
